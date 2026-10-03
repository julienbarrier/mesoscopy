"""Read a (possibly still running) QCoDeS run through a separate read-only connection (no Qt)."""
import os

import numpy as np
from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect
from qcodes.dataset.sqlite.queries import get_runs


def next_run_id(db_path):
    """run_id the next run of this database will get (1 for an empty or missing database)."""
    if not os.path.isfile(db_path):
        return 1
    conn = connect(db_path, read_only=True)
    try:
        return max(get_runs(conn), default=0) + 1
    finally:
        conn.close()


def previous_run_ids(db_path, run_id, count):
    """Ids of the ``count`` runs before ``run_id`` in the same experiment, oldest first (empty when there are none)."""
    if count <= 0 or not os.path.isfile(db_path):
        return []
    conn = connect(db_path, read_only=True)
    try:
        if run_id not in get_runs(conn):
            return []
        earlier = [r for r in get_runs(conn, load_by_id(run_id, conn=conn).exp_id) if r < run_id]
        return sorted(earlier)[-count:]
    finally:
        conn.close()


def _single_curve(data, specs):
    """The run is one curve: a sweep of one axis, or one trace (no sweep axis behind it). Anything else holds several
    curves (the inner sweeps, or one trace per point), which the plot draws as rows."""
    for dependent, columns in data.items():
        axes = [n for n in columns if n != dependent and specs[n].type != "array"]
        if len(axes) > (0 if specs[dependent].type == "array" else 1):
            return False
    return True


def _row_length(values, rows):
    """Points of one trace in a column of arrays: the last dimension of a (rows, points) array, or, when the data of a
    run in progress comes flat, its size divided by the number of acquisitions written so far."""
    if values.ndim > 1:
        return int(values.shape[-1])
    return max(int(values.size // max(rows, 1)), 1)


def fetch_run_data(db_path, run_id):
    """Everything the live plot needs from one run, or None if the run is not in the database yet.

    ``arrays`` maps each plottable parameter (swept and measured) to a flat float array in
    acquisition order. While a run is in progress QCoDeS returns flat arrays; they are
    flattened here as well for finished runs, which come back reshaped to the sweep grid.
    Complex parameters stay complex (the plot draws both parts); text parameters are skipped.
    """
    if not os.path.isfile(db_path):
        return None
    conn = connect(db_path, read_only=True)
    try:
        if run_id not in get_runs(conn):
            return None
        ds = load_by_id(run_id, conn=conn)
        data = ds.get_parameter_data()
        specs = ds.paramspecs
        arrays, setpoints, row_lengths = {}, [], {}
        for dependent, columns in data.items():
            for name, values in columns.items():
                if name in arrays:
                    continue
                values = np.asarray(values)
                if not np.issubdtype(values.dtype, np.number):
                    continue
                if specs[name].type == "array":  # a trace, or the axis of one: one row per acquisition
                    row_lengths[name] = _row_length(values, ds.number_of_results)
                arrays[name] = values.astype(complex if np.iscomplexobj(values) else float).ravel()
                if name not in data:
                    setpoints.append(name)
        dependents = [name for name in data if name in arrays]
        labels = {
            name: f"{specs[name].label or name} ({specs[name].unit})" if specs[name].unit
            else (specs[name].label or name)
            for name in arrays
        }
        return {
            "run_id": ds.captured_run_id,
            "name": ds.name,
            "completed": bool(ds.completed),
            "single_curve": _single_curve(data, specs),
            "arrays": arrays,
            "labels": labels,
            "units": {name: specs[name].unit for name in arrays},
            "setpoints": setpoints,
            "dependents": dependents,
            "n_points": min((len(a) for a in arrays.values()), default=0),
            # traces: points of one trace, and which columns are traces (values) or their axes
            "trace_length": next(iter(row_lengths.values()), None),
            "trace_values": [n for n in dependents if n in row_lengths],
            "trace_axes": [n for n in setpoints if n in row_lengths],
        }
    finally:
        conn.close()
