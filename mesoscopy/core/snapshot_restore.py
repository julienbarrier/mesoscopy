"""Set the application up as it was for a past run, from the snapshot QCoDeS stored with it (no Qt).

Four steps, each planned before anything is changed so that the user can review it:

1. instruments of the snapshot that are not loaded are connected (``plan_instruments``),
2. the experiment parameters the run needed are created (``plan_definitions``),
3. the settable parameters of the instruments are set to their values in the snapshot (``plan_values``),
4. the Measurement tab is set up from what mesoscopy recorded (``run_setup``), or, for runs made
   without mesoscopy, rebuilt from the data of the run (``infer_setup``).
"""
import math
import re
from dataclasses import dataclass, field

import numpy as np
import yaml
from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect
from qcodes.instrument import InstrumentBase
from qcodes.instrument.channel import ChannelTuple
from qcodes.parameters import DelegateParameter

from mesoscopy.core.experiment_parameters import ParameterDefinition, instruments_of
from mesoscopy.core.parameter_io import collect_parameters, get_children, zhinst_node_is_read_only
from mesoscopy.core.run_setup import required_definitions, setup_of_snapshot


# ================= reading the run =================
@dataclass
class RunRecord:
    run_id: int
    experiment: str
    sample: str
    measurement: str
    completed: bool
    snapshot: dict | None            # what QCoDeS stored: {"station": {...}}
    setup: dict | None               # what mesoscopy recorded in it (None: not run with mesoscopy)
    layout: dict | None = None       # data of the run (read only when there is no recorded setup)


def read_run(db_path, run_id):
    """Read what a run stored: names, snapshot, mesoscopy setup and, if that is missing, the layout of its data.

    The database is opened read-only. Raises whatever QCoDeS raises if the run cannot be read.
    """
    conn = connect(db_path, read_only=True)
    try:
        dataset = load_by_id(run_id, conn=conn)
        snapshot = dataset.snapshot
        setup = setup_of_snapshot(snapshot)
        return RunRecord(
            run_id=dataset.captured_run_id, experiment=dataset.exp_name, sample=dataset.sample_name or "",
            measurement=dataset.name, completed=bool(dataset.completed), snapshot=snapshot, setup=setup,
            layout=None if setup is not None else _read_layout(dataset),
        )
    finally:
        conn.close()


def _read_layout(dataset):
    """Measured (dependent) parameters and the distinct values of the swept ones, outermost first.

    This is all that is known of a run made by a plain ``dond`` call: the setpoints are registered
    in the order of the sweeps, outermost first.
    """
    dependencies = dataset.description.interdeps.dependencies
    dependents = [spec.name for spec in dependencies]
    swept = []
    for specs in dependencies.values():
        swept += [spec.name for spec in specs if spec.name not in swept]
    if not dependents:
        return {"dependents": [], "axes": [], "rows": 0}
    data = dataset.get_parameter_data(*dependents)
    axes, rows = [], 0
    for name in swept:
        for block in data.values():
            if name in block:
                values = np.asarray(block[name], dtype=float).ravel()
                rows = max(rows, len(values))
                _, first = np.unique(values, return_index=True)
                axes.append((name, values[np.sort(first)]))  # distinct values, in order of appearance
                break
    return {"dependents": dependents, "axes": axes, "rows": rows}


# ================= 1. instruments =================
@dataclass
class InstrumentPlan:
    """An instrument of the snapshot that is not loaded in the station."""
    name: str
    type: str
    source: str          # "station file", "run snapshot" (the entry stored with the run) or "" (cannot be loaded)
    entry: dict = field(default_factory=dict)

    def describe(self):
        origin = {"station file": "from the station file", "run snapshot": "from the entry stored with the run",
                  "": "NOT AVAILABLE: not described in the station file or in the run"}[self.source]
        return f"{self.name} ({self.type or 'unknown type'}), {origin}"


def plan_instruments(station, station_entries, snapshot):
    """The instruments of ``snapshot`` that are not loaded, and where their definition comes from.

    ``station_entries`` is the ``instruments`` section of the station file in use.
    """
    stored = ((snapshot or {}).get("station") or {})
    stored_entries = (stored.get("config") or {}).get("instruments") or {}
    plans = []
    for name in (stored.get("instruments") or {}):
        if name in station.components:
            continue
        if name in station_entries:
            plans.append(InstrumentPlan(name, station_entries[name].get("type", ""), "station file"))
        elif name in stored_entries:
            plans.append(InstrumentPlan(name, stored_entries[name].get("type", ""), "run snapshot",
                                        stored_entries[name]))
        else:
            plans.append(InstrumentPlan(name, "", ""))
    return plans


def add_stored_entries(station, station_entries, plans):
    """Make the instruments that only the run's snapshot describes loadable in the station.

    Returns the new ``instruments`` section: the station file's entries plus the stored ones.
    """
    extra = {p.name: p.entry for p in plans if p.source == "run snapshot"}
    if not extra:
        return station_entries
    merged = {**station_entries, **extra}
    station.load_config(yaml.safe_dump({"instruments": merged}))
    return merged


# ================= 2. experiment parameters =================
@dataclass
class DefinitionChange:
    definition: ParameterDefinition
    status: str                                  # "new", "changed" or "same"
    current: ParameterDefinition | None = None
    checked: bool = True

    def differences(self):
        """What differs from the current definition, e.g. 'gain 1 -> 0.5; max_value 5 -> 2'."""
        if self.current is None:
            return ""
        old, new = self.current.to_dict(), self.definition.to_dict()
        parts = []
        for key in new:
            if key == "origin" or old.get(key) == new[key]:
                continue
            if key == "breakout":
                parts.append(f"breakout {self.current.breakout.describe(self.current.name) if self.current.breakout.enabled else 'off'}"
                             f" -> {self.definition.breakout.describe(self.definition.name) if self.definition.breakout.enabled else 'off'}")
            else:
                parts.append(f"{key} {old.get(key)} -> {new[key]}")
        return "; ".join(parts)


def plan_definitions(registry, definitions):
    """Compare the definitions the run needed (dicts) with the ones in the registry."""
    changes = []
    for data in definitions:
        definition = ParameterDefinition.from_dict(data)
        current = registry.definitions.get(definition.name)
        if current is None:
            changes.append(DefinitionChange(definition, "new"))
            continue
        same = {k: v for k, v in current.to_dict().items() if k != "origin"} == \
               {k: v for k, v in definition.to_dict().items() if k != "origin"}
        definition.origin = current.origin  # where it comes from now does not change
        changes.append(DefinitionChange(definition, "same" if same else "changed", current, checked=True))
    return changes


def apply_definitions(registry, changes):
    """Create the new definitions and replace the changed ones. Returns the problems (one text each)."""
    problems = []
    for change in changes:
        if not change.checked or change.status == "same":
            continue
        try:
            if change.status == "new":
                registry.add(change.definition)
            else:
                registry.update(change.definition)
        except ValueError as e:
            problems.append(f"experiment parameter {change.definition.name}: {e}")
    return problems


# ================= 3. instrument values =================
@dataclass
class ValueChange:
    """A settable instrument parameter whose value differs from the one in the snapshot."""
    label: str                   # instrument.submodule.parameter
    parameter: object
    current: object              # None when it cannot be read
    target: object
    checked: bool = True


def _same(a, b):
    """True if two parameter values are equal (floats compared with a small tolerance)."""
    if a is None or b is None:
        return False
    try:
        if isinstance(a, str) or isinstance(b, str):
            return str(a) == str(b)
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return bool(a == b)


def _plannable(parameter, target):
    """Only plain values of parameters that can really be set are restored."""
    if target is None or isinstance(target, (dict, list, tuple)):
        return False
    if isinstance(parameter, DelegateParameter):  # an alias: the parameter it points to is restored
        return False
    return bool(parameter.settable) and not zhinst_node_is_read_only(parameter) \
        and not getattr(parameter, "snapshot_exclude", False)


def _walk(stored, live, path, changes):
    """Compare the stored snapshot of a node with the live node, parameters first, then sub-modules."""
    parameters = getattr(live, "parameters", None) or {}
    for name, entry in (stored.get("parameters") or {}).items():
        parameter = parameters.get(name)
        if parameter is None or not _plannable(parameter, entry.get("value")):
            continue
        try:
            current = parameter.cache.get(get_if_invalid=True)  # reads the instrument only if nothing is cached
        except Exception:
            current = None
        if not _same(current, entry["value"]):
            changes.append(ValueChange(".".join((*path, name)), parameter, current, entry["value"]))
    submodules = getattr(live, "submodules", None) or {}
    for name, entry in (stored.get("submodules") or {}).items():
        child = submodules.get(name)
        if isinstance(child, ChannelTuple):  # channels stored under their short name
            for short_name, channel_entry in (entry.get("channels") or {}).items():
                channel = get_children(child).get(short_name)
                if channel is not None:
                    _walk(channel_entry, channel, (*path, name, short_name), changes)
        elif child is not None:
            _walk(entry, child, (*path, name), changes)


def plan_values(station, snapshot, only=None):
    """The settable parameters of the loaded instruments whose value differs from the snapshot's
    (only the instruments named in ``only``, if given).

    Reading the current values talks to the instruments (parameters never read before), like taking a
    snapshot does. Nothing is set here.
    """
    changes = []
    instruments = ((snapshot or {}).get("station") or {}).get("instruments") or {}
    for name, stored in instruments.items():
        if only is not None and name not in only:
            continue
        live = instruments_of(station).get(name)
        if live is not None:
            _walk(stored, live, (name,), changes)
    return changes


def value_routes(registry):
    """{id(instrument parameter): (experiment parameter, definition)} for the experiment parameters on settable
    instrument parameters. Setting through them applies their safe limits and maximum ramp rate."""
    routes = {}
    for name, parameter in registry.parameters().items():
        definition = registry.definitions.get(name)
        source = getattr(parameter, "source", None)
        if definition is not None and definition.kind == "instrument" and source is not None and parameter.settable:
            routes[id(source)] = (parameter, definition)
    return routes


def _set_value(change, routes):
    route = routes.get(id(change.parameter))
    numeric = isinstance(change.target, (int, float)) and not isinstance(change.target, bool)
    if route is not None and numeric:
        delegate, definition = route
        delegate.set(change.target * definition.gain)  # value = source value x gain; ramps within the limits
    else:
        change.parameter.set(change.target)


def apply_values(changes, routes=None, on_progress=None):
    """Set the parameters. Returns (number set, problems).

    A parameter that is refused (a range or a mode set later may be needed first) is tried again once
    the others are set, for as long as that makes progress.
    """
    routes = routes or {}
    pending = [c for c in changes if c.checked]
    total, done, failures = len(pending), 0, []
    while pending:
        failures = []
        for change in pending:
            try:
                _set_value(change, routes)
                done += 1
                if on_progress:
                    on_progress(done, total)
            except Exception as e:
                failures.append((change, e))
        if len(failures) == len(pending):  # nothing was accepted in this pass: stop
            break
        pending = [c for c, _ in failures]
        failures = [] if not pending else failures
    problems = [f"{c.label}: {type(e).__name__}: {e}" for c, e in failures]
    return done, problems


# ================= 4. runs made without mesoscopy =================
_NAME = re.compile(r"\W")


def _axis_state(values):
    """Sweep fields reproducing the distinct values of an axis: linear, logarithmic or an explicit array."""
    values = np.asarray(values, dtype=float)
    count = len(values)
    state = {"num": count, "start": repr(float(values[0])), "stop": repr(float(values[-1]))}
    if count < 3 or np.allclose(np.diff(values), (values[-1] - values[0]) / (count - 1)):
        return {"class": "LinSweep", **state}
    if np.all(values > 0) and np.allclose(np.diff(np.log10(values)), np.log10(values[-1] / values[0]) / (count - 1)):
        return {"class": "LogSweep", **state}
    return {"class": "ArraySweep", "array": f"np.array({[float(v) for v in values]!r})"}


def infer_setup(layout, registry, station, record):
    """Rebuild the Measurement tab setup of a run made without mesoscopy from the data it holds.

    Returns (setup, problems). The sweeps and the measured parameters are named in the dataset by the
    parameter's registered name: they are looked up among the experiment parameters, then among all
    the parameters of the loaded instruments (for which an experiment parameter is created). What a
    dataset does not hold is not restored: the delay of the sweeps, bidirectional sweeps (each value
    is counted once) and sweeps done together.
    """
    problems = []
    known = {p.register_name: name for name, p in registry.parameters().items()}
    known.update({name: name for name in registry.parameters()})
    instrument_parameters = None
    new_definitions = []

    def find(register_name):
        nonlocal instrument_parameters
        if register_name in known:
            return known[register_name]
        if instrument_parameters is None:
            instrument_parameters = {}
            for instrument_name, instrument in instruments_of(station).items():
                for path, parameter in collect_parameters(instrument, (instrument_name,), True, 10 ** 6)[0]:
                    instrument_parameters.setdefault(parameter.register_name, (path, parameter))
        if register_name not in instrument_parameters:
            return None
        path, parameter = instrument_parameters[register_name]
        name = _NAME.sub("_", register_name)
        used = set(registry.definitions) | {d["name"] for d in new_definitions}
        while name in used:
            name += "_"
        new_definitions.append(ParameterDefinition(name=name, source=list(path), unit=parameter.unit or "").to_dict())
        known[register_name] = name
        return name

    dimensions = []
    axes = layout["axes"]
    if axes and math.prod(len(values) for _, values in axes) != layout["rows"]:
        problems.append("the sweeps could not be rebuilt from the data (run not finished, or sweeps done "
                        "together): set them up by hand")
        axes = []
    for register_name, values in axes:
        name = find(register_name)
        if name is None:
            problems.append(f"swept parameter {register_name} is not among the loaded instruments' parameters")
            dimensions = []
            break
        dimensions.append({**_axis_state(values), "component": [name]})
    measured = []
    for register_name in layout["dependents"]:
        name = find(register_name)
        if name is None:
            problems.append(f"measured parameter {register_name} is not among the loaded instruments' parameters")
        else:
            measured.append({"alias": register_name if register_name != name else "", "path": [name]})
    sweep = {"experiment_name": record.experiment, "measurement_name": record.measurement,
             "dimensions": dimensions, "measured": measured}
    return {"version": 1, "inferred": True, "experiment_parameters": new_definitions, "sweep": sweep,
            "sample_name": record.sample}, problems


def setup_for(record, registry, station):
    """(setup, problems, how): the setup of the run and how it is known ("recorded" or "inferred from the data")."""
    if record.setup is not None:
        return record.setup, [], "recorded by mesoscopy"
    if record.layout is None:
        return None, [], ""
    setup, problems = infer_setup(record.layout, registry, station, record)
    return setup, problems, "inferred from the data (best effort)"


def definitions_to_restore(setup):
    """The definitions (dicts) a setup needs: the recorded ones the sweeps use, or the inferred new ones."""
    return list(setup["experiment_parameters"]) if setup.get("inferred") else required_definitions(setup)
