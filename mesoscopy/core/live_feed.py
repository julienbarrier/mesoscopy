"""Live data of a run in progress, pushed by QCoDeS instead of read back from the database (no Qt).

``dond`` builds its own ``Measurement``, so there is no handle on its dataset. ``capture_live_runs`` swaps in a
``Measurement`` that, when a run starts, hands a ``LiveRun`` to the caller and subscribes it to the dataset:

* a sweep of more than one dimension: QCoDeS' in-memory cache (``dataset.cache.data()``) already holds the whole grid
  (missing points are NaN); the subscriber only counts the points written, so a line trace shows as soon as its
  first points are flushed and a map is only redrawn when new points arrived;
* a one-dimensional sweep or a trace (ParameterWithSetpoints): the rows the subscriber receives are appended to growing
  buffers, so the run is never read again;
* the in-memory cache switched off: the buffers are used for every run.

``LiveRun.snapshot()`` returns the dict ``core.live_data.fetch_run_data`` returns, so the plot does not care where
the data came from. Nothing here may ever disturb a measurement: failures are swallowed and the plot falls back to
reading the database.
"""
import threading
from contextlib import contextmanager

import numpy as np
from qcodes.dataset.sqlite.database import _convert_array, _convert_complex

from mesoscopy.core.live_data import _single_curve

_MIN_CAPACITY = 1024


class _Buffer:
    """An array (float, or complex) that grows by doubling; ``view`` is a copy-free window on what was filled."""

    def __init__(self, dtype=float):
        self._dtype = dtype
        self._data = np.empty(_MIN_CAPACITY, dtype=dtype)
        self.size = 0

    def extend(self, values):
        values = np.asarray(values, dtype=self._dtype).ravel()
        end = self.size + values.size
        if end > self._data.size:
            grown = np.empty(max(end, 2 * self._data.size), dtype=self._dtype)
            grown[:self.size] = self._data[:self.size]
            self._data = grown
        self._data[self.size:end] = values
        self.size = end

    def view(self, size=None):
        return self._data[:self.size if size is None else size]


def _number(value):
    """A value of the results table as a float or complex (the table holds NULL and 'nan' for missing values)."""
    if value is None:
        return np.nan
    if isinstance(value, (bytes, bytearray)):  # a complex number is stored as a small array
        value = _convert_complex(value)
    try:
        return complex(value) if isinstance(value, (complex, np.complexfloating)) else float(value)
    except (TypeError, ValueError):
        return np.nan


class LiveRun:
    """The data of one dataset as it is written. Filled by the subscriber thread, read by the GUI thread."""

    def __init__(self, on_change=None):
        self.on_change = on_change  # called (from the subscriber thread) when rows arrive, and when the run ends
        self.state = {}             # QCoDeS wants a mutable state for the subscriber
        self.run_id = None
        self.ready = False
        self.completed = False
        self.version = 0            # grows with every change: the plot redraws only if it moved
        self.uses_cache = False
        self._lock = threading.Lock()
        self._dataset = None
        self._frozen = None         # the arrays of a finished run read from the cache
        self._rows = 0

    # ----- set up (measurement thread, when the dataset exists) -----
    def attach(self, dataset):
        specs = {spec.name: spec for spec in dataset.get_parameters()}
        interdeps = dataset.description.interdeps
        tree = {}  # dependent -> its columns (itself first), like the keys of ``get_parameter_data``
        for top in interdeps.top_level_parameters:
            top, dependencies, inferred = interdeps.all_parameters_in_tree_by_group(top)
            tree[top.name] = [top.name, *(p.name for p in dependencies), *(p.name for p in inferred)]
        self._dataset, self._specs, self._tree = dataset, specs, tree
        self._columns = list(specs)  # the order of the values the subscriber receives
        self._plotted = {n: s for n, s in specs.items() if s.type in ("numeric", "array", "complex")}
        # one column per name, in tree order, like fetch_run_data
        self._names = list(dict.fromkeys(n for columns in tree.values() for n in columns if n in self._plotted))
        self._has_arrays = any(s.type == "array" for s in self._plotted.values())
        axes = {n for columns in tree.values() for n in columns[1:] if n in self._plotted}
        self.uses_cache = (not self._has_arrays and len(axes) >= 2
                           and bool(getattr(dataset, "_in_memory_cache", False)))
        if not self.uses_cache:
            self._buffers = {n: _Buffer(complex if specs[n].type == "complex" else float) for n in self._names}
        self._trace_length = None
        self.run_id = dataset.run_id
        self._captured_run_id, self._name = dataset.captured_run_id, dataset.name
        self.ready = True

    # ----- the subscriber (QCoDeS' subscriber thread) -----
    def on_rows(self, rows, length, state):
        if not self.ready or not rows:
            return
        try:
            with self._lock:
                if self.uses_cache:
                    self._rows += len(rows)
                else:
                    for row in rows:
                        self._append(row)
                self.version += 1
        except Exception:
            return
        if self.on_change is not None:
            self.on_change()

    def _append(self, row):
        values = {}
        for name, value in zip(self._columns, row):
            if name in self._plotted:
                is_array = self._specs[name].type == "array"
                values[name] = _convert_array(value) if is_array and isinstance(value, (bytes, bytearray)) else value
        if self._has_arrays:  # a trace: one row per acquisition, the scalars are repeated along it (as QCoDeS does)
            length = max((np.size(v) for n, v in values.items() if self._specs[n].type == "array"), default=1)
            self._trace_length = self._trace_length or length
            for name, buffer in self._buffers.items():
                value = values.get(name)
                buffer.extend(value if self._specs[name].type == "array" else np.full(length, _number(value)))
        else:
            for name, buffer in self._buffers.items():
                buffer.extend([_number(values.get(name))])
        self._rows += 1

    def finish(self):
        """The dataset is complete: the last rows were delivered when the subscribers were removed."""
        if self.uses_cache:  # keep the arrays, let go of the dataset (and with it of its connection and cache)
            try:
                with self._lock:
                    self._frozen = self._cache_arrays(self._rows)
                    self._dataset = None
            except Exception:
                self._frozen = None
        self.completed = True
        self.version += 1
        if self.on_change is not None:
            self.on_change()

    # ----- reading (GUI thread) -----
    def snapshot(self):
        """What the plot needs, as ``fetch_run_data`` gives it, or None while there is nothing to draw yet."""
        if not self.ready:
            return None
        try:
            with self._lock:
                rows, version, completed = self._rows, self.version, self.completed
                if rows == 0:
                    return None
                arrays = (self._frozen or self._cache_arrays(rows)) if self.uses_cache else {n: b.view() for n, b in self._buffers.items()}
            if not arrays:
                return None
        except Exception:
            return None
        return self._describe(arrays, version, completed)

    def _cache_arrays(self, rows):
        cache = self._dataset.cache
        if not cache.live:  # never ask a cache that is not live: it would read the database from this thread
            return {}
        data, arrays = cache.data(), {}
        for dependent, columns in data.items():
            for name, values in columns.items():
                if name in self._names and name not in arrays:
                    kind = complex if self._specs[name].type == "complex" else float
                    flat = np.asarray(values, dtype=kind).ravel()  # the grid in acquisition order (NaN: not yet measured)
                    arrays[name] = flat[:rows]
        return arrays

    def _describe(self, arrays, version, completed):
        specs, tree = self._specs, self._tree
        trace_names = [n for n in self._names if specs[n].type == "array"]
        dependents = [n for n in tree if n in arrays]
        setpoints = [n for n in self._names if n in arrays and n not in tree]
        return {
            "run_id": self._captured_run_id,
            "name": self._name,
            "completed": completed,
            "version": version,
            "single_curve": _single_curve(tree, specs),
            "arrays": arrays,
            "labels": {n: f"{specs[n].label or n} ({specs[n].unit})" if specs[n].unit else (specs[n].label or n)
                      for n in arrays},
            "units": {n: specs[n].unit for n in arrays},
            "setpoints": setpoints,
            "dependents": dependents,
            "n_points": min((len(a) for a in arrays.values()), default=0),
            "trace_length": self._trace_length if trace_names else None,
            "trace_values": [n for n in dependents if n in trace_names],
            "trace_axes": [n for n in setpoints if n in trace_names],
        }


class _LiveContext:
    """What ``Measurement.run()`` returns, wrapped: hands the dataset to the ``LiveRun`` once it exists."""

    def __init__(self, runner, live, announce):
        self._runner, self._live, self._announce = runner, live, announce

    def __enter__(self):
        datasaver = self._runner.__enter__()
        try:
            self._live.attach(datasaver.dataset)
            self._announce(self._live)
        except Exception:
            self._live.ready = False  # the plot reads the database instead
        return datasaver

    def __exit__(self, *exc):
        try:
            return self._runner.__exit__(*exc)
        finally:
            if self._live.ready:
                self._live.finish()

    def __getattr__(self, name):
        return getattr(self._runner, name)


@contextmanager
def capture_live_runs(announce, on_change=None):
    """Within the block, every run ``dond`` starts calls ``announce(live_run)`` (from the measurement thread).
    ``on_change()`` is called (from the subscriber thread) whenever one of them has new rows or ends."""
    from qcodes.dataset.dond import do_nd
    original = do_nd.Measurement

    class _LiveMeasurement(original):
        def run(self, *args, **kwargs):
            live = LiveRun(on_change)
            self.add_subscriber(live.on_rows, live.state)
            return _LiveContext(super().run(*args, **kwargs), live, announce)

    do_nd.Measurement = _LiveMeasurement
    try:
        yield
    finally:
        do_nd.Measurement = original
