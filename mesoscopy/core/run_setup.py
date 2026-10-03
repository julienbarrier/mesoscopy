"""What mesoscopy records next to the QCoDeS snapshot of a run, and how to read it back (no Qt).

QCoDeS stores ``station.snapshot()`` with every run. It contains the instruments with all their
parameters, the root parameters and the station file, but not what only mesoscopy knows: the
definitions of the experiment parameters (expressions, breakout conditions) and the setup of the
Measurement tab. That is put in ``station.metadata`` just before a run starts, which QCoDeS adds to
the snapshot under ``snapshot["station"]["metadata"]["mesoscopy"]``.
"""
from mesoscopy.core.dond_options import names_used
from mesoscopy.core.experiment_parameters import expression_names

SETUP_KEY = "mesoscopy"
SETUP_VERSION = 1


def build_setup(registry, sweep_state, sample_name=""):
    """The setup to record: all experiment parameter definitions and the state of the Measurement tab."""
    return {
        "version": SETUP_VERSION,
        "sample_name": sample_name,
        "experiment_parameters": [d.to_dict() for d in registry.definitions.values()],
        "sweep": sweep_state,
    }


def record_setup(station, setup):
    """Put the setup in the station metadata: the snapshot QCoDeS takes when the run starts includes it."""
    station.metadata[SETUP_KEY] = setup


def setup_of_snapshot(snapshot):
    """The mesoscopy setup recorded in a run's snapshot, or None (older runs, runs made by other code)."""
    metadata = ((snapshot or {}).get("station") or {}).get("metadata") or {}
    setup = metadata.get(SETUP_KEY)
    return setup if isinstance(setup, dict) and "sweep" in setup else None


def required_definitions(setup):
    """The experiment parameter definitions (dicts) the recorded measurement needs, dependencies first.

    These are the parameters used by the sweeps and the measured parameters, the ones they are derived
    from and, when the run stopped on breakout conditions, the parameters with such a condition.
    """
    definitions = {d["name"]: d for d in setup.get("experiment_parameters", [])}
    sweep = setup.get("sweep") or {}
    names = set()
    for dimension in sweep.get("dimensions", []):
        for path in [dimension.get("component"), *dimension.get("together", [])]:
            if path:
                names.add(path[0])
    for measured in sweep.get("measured", []):
        if measured.get("path"):
            names.add(measured["path"][0])
    advanced = sweep.get("advanced") or {}
    names |= {n for n in advanced.get("setpoints") or [] if n in definitions}
    # the experiment parameters that the code of the actions uses by name
    actions = [*advanced.get("enter", []), *advanced.get("exit", [])]
    for dimension in sweep.get("dimensions", []):
        actions += dimension.get("actions") or []
    names |= {n for n in names_used(actions) if n in definitions}
    if sweep.get("breakout"):
        names |= {n for n, d in definitions.items() if (d.get("breakout") or {}).get("enabled")}
    todo = list(names)
    while todo:
        definition = definitions.get(todo.pop())
        if definition and definition.get("kind") == "derived":
            try:
                used = expression_names(definition.get("expression", ""))
            except SyntaxError:
                continue
            for name in used:
                if name in definitions and name not in names:
                    names.add(name)
                    todo.append(name)
    return [d for name, d in definitions.items() if name in names]  # creation order: dependencies first
