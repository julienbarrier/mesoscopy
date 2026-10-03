"""Read a (possibly still running) QCoDeS run through a separate read-only connection (no Qt)."""
import os

import numpy as np
from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect
from qcodes.dataset.sqlite.queries import get_runs

from mesoscopy.core.grid_data import compact_grid


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


def _tree(ds):
    """{dependent: its columns (itself first)} from the description of the run: the shape of the data, without reading it."""
    interdeps = ds.description.interdeps
    tree = {}
    for top in interdeps.top_level_parameters:
        top, dependencies, inferred = interdeps.all_parameters_in_tree_by_group(top)
        tree[top.name] = [top.name, *(p.name for p in dependencies), *(p.name for p in inferred)]
    return tree


def fetch_run_data(db_path, run_id, curves_only=False):
    """Everything the live plot needs from one run, or None if the run is not in the database yet.

    ``arrays`` maps each plottable parameter (swept and measured) to a flat float array in
    acquisition order. While a run is in progress QCoDeS returns flat arrays; they are
    flattened here as well for finished runs, which come back reshaped to the sweep grid.
    Complex parameters stay complex (the plot draws both parts); text parameters are skipped.

    A finished run of two or more dimensions is kept compact (``core/grid_data``: the unique values of each axis and the
    value matrix in 32 bits). ``curves_only``: for the faded earlier runs, which are only drawn when they are a single
    curve: any other run is answered without reading its data.
    """
    if not os.path.isfile(db_path):
        return None
    conn = connect(db_path, read_only=True)
    try:
        if run_id not in get_runs(conn):
            return None
        ds = load_by_id(run_id, conn=conn)
        specs = ds.paramspecs
        if curves_only and not _single_curve(_tree(ds), specs):
            return {"run_id": ds.captured_run_id, "name": ds.name, "completed": bool(ds.completed), "single_curve": False,
                    "arrays": {}}
        data = ds.get_parameter_data()
        arrays, setpoints, row_lengths, shaped = {}, [], {}, {}
        for dependent, columns in data.items():
            for name, values in columns.items():
                if name in arrays or name in shaped:
                    continue
                values = np.asarray(values)
                if not np.issubdtype(values.dtype, np.number):
                    continue
                if specs[name].type == "array":  # a trace, or the axis of one: one row per acquisition
                    row_lengths[name] = _row_length(values, ds.number_of_results)
                if ds.completed and values.ndim >= 2 and specs[name].type != "array":
                    shaped[name] = values  # a finished map: kept compact below
                else:
                    arrays[name] = values.astype(complex if np.iscomplexobj(values) else float).ravel()
                if name not in data:
                    setpoints.append(name)
        if shaped:
            arrays.update(compact_grid(shaped, set(data)))
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
