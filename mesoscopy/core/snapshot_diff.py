"""What differs between the snapshots of two runs (no Qt).

The snapshots are compared as flat lists of values: the parameters of the instruments (their value), the parameters
at the root of the station, and what mesoscopy recorded with the run (the experiment parameter definitions and the
Measurement tab setup). Only what differs is reported, as rows in the style of the instrument snapshot: groups
(instrument, module, ...) with the differing parameters under them.
"""
import math
import os
from dataclasses import dataclass

from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect

from mesoscopy.core.parameter_io import format_value
from mesoscopy.core.run_setup import setup_of_snapshot

ABSENT = "(absent)"
ROOT_PARAMETERS = "station parameters"
EXPERIMENT_PARAMETERS = "experiment parameters"
SETUP = "measurement setup"


@dataclass
class RunSnapshot:
    db_name: str
    experiment: str
    run_id: int
    run_name: str
    snapshot: dict | None


def read_run_snapshot(db_path, run_id):
    """The snapshot of a run with the names that identify it. The database is opened read-only."""
    conn = connect(db_path, read_only=True)
    try:
        dataset = load_by_id(run_id, conn=conn)
        return RunSnapshot(os.path.basename(db_path), dataset.exp_name, dataset.captured_run_id, dataset.name,
                           dataset.snapshot)
    finally:
        conn.close()


# ----- flattening -----
def _walk_instrument(node, path, out):
    for name, entry in (node.get("parameters") or {}).items():
        if isinstance(entry, dict) and "value" in entry:
            out[(*path, name)] = entry["value"]
    for name, entry in (node.get("submodules") or {}).items():
        if not isinstance(entry, dict):
            continue
        _walk_instrument(entry, (*path, name), out)
        for channel, channel_entry in (entry.get("channels") or {}).items():
            _walk_instrument(channel_entry, (*path, name, channel), out)


def _flatten(value, path, out):
    """Nested dicts and lists as {path: scalar}; a list item is a path element ``name[index]``."""
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(item, (*path, str(key)), out)
    elif isinstance(value, (list, tuple)):
        if path and all(not isinstance(v, (dict, list, tuple)) for v in value):
            out[path] = ", ".join(format_value(v) for v in value)  # a short list is one value
        else:
            for index, item in enumerate(value):
                _flatten(item, (*path[:-1], f"{path[-1]}[{index}]") if path else (f"[{index}]",), out)
    else:
        out[path] = value


def flatten_snapshot(snapshot):
    """{path tuple: value} of everything compared in a snapshot (empty for a run without one)."""
    out = {}
    station = (snapshot or {}).get("station") or {}
    for name, node in (station.get("instruments") or {}).items():
        _walk_instrument(node, (name,), out)
    for name, entry in (station.get("parameters") or {}).items():
        if isinstance(entry, dict) and "value" in entry:
            out[(ROOT_PARAMETERS, name)] = entry["value"]
    setup = setup_of_snapshot(snapshot)
    if setup:
        definitions = {d["name"]: d for d in setup.get("experiment_parameters", []) if "name" in d}
        _flatten(definitions, (EXPERIMENT_PARAMETERS,), out)
        _flatten(setup.get("sweep") or {}, (SETUP,), out)
    return out


# ----- comparing -----
def same(a, b):
    """True if two values are the same (floats compared with a small tolerance)."""
    if a is ABSENT or b is ABSENT:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return a == b
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return a == b


def diff_rows(snapshot_a, snapshot_b):
    """Rows (dicts: depth, name, a, b, group) of what differs: each group row is followed by the differing
    parameters under it. Nothing is returned for what is identical."""
    flat_a, flat_b = flatten_snapshot(snapshot_a), flatten_snapshot(snapshot_b)
    paths = list(flat_a) + [p for p in flat_b if p not in flat_a]
    differing = [p for p in paths if not same(flat_a.get(p, ABSENT), flat_b.get(p, ABSENT))]
    rows, opened = [], []
    for path in differing:
        for depth, name in enumerate(path[:-1]):
            if opened[:depth + 1] != list(path[:depth + 1]):
                opened = list(path[:depth + 1])
                rows.append({"depth": depth, "name": name, "a": "", "b": "", "group": True})
        rows.append({
            "depth": len(path) - 1, "name": path[-1], "group": False,
            "a": ABSENT if path not in flat_a else format_value(flat_a[path]),
            "b": ABSENT if path not in flat_b else format_value(flat_b[path]),
        })
    return rows


def describe_runs(a, b):
    """Lines that say which two runs are compared: database, experiment and run id of each, without repeating what
    they have in common."""
    if a.db_name == b.db_name and a.experiment == b.experiment:
        return [f"Database {a.db_name}, experiment {a.experiment}", f"Run A: {a.run_id}", f"Run B: {b.run_id}"]
    if a.db_name == b.db_name:
        return [f"Database {a.db_name}", f"Run A: experiment {a.experiment}, run {a.run_id}",
                f"Run B: experiment {b.experiment}, run {b.run_id}"]
    if a.experiment == b.experiment:
        return [f"Experiment {a.experiment}", f"Run A: database {a.db_name}, run {a.run_id}",
                f"Run B: database {b.db_name}, run {b.run_id}"]
    return [f"Run A: {a.db_name} / {a.experiment} / run {a.run_id}", f"Run B: {b.db_name} / {b.experiment} / run {b.run_id}"]


def diff_to_text(header, rows):
    """The runs compared and the differences as aligned text, for a lab notebook or a bug report."""
    width = max((2 * r["depth"] + len(r["name"]) for r in rows if not r["group"]), default=0)
    col_a = max((len(r["a"]) for r in rows if not r["group"]), default=len("Run A"))
    lines = list(header) + [""]
    for row in rows:
        indent = "  " * row["depth"]
        if row["group"]:
            lines.append(f"{indent}{row['name']}:")
        else:
            lines.append(f"{indent}{row['name']:<{width - len(indent)}}  {row['a']:<{col_a}}  {row['b']}")
    if not rows:
        lines.append("No difference.")
    return "\n".join(lines)
