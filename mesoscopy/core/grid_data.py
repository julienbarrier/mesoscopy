"""Compact copies of the data of a finished multi-dimensional run, for the live plot (no Qt).

QCoDeS stores a map as one column per parameter, every column as long as the whole grid: a 1000 x 1000 map with two
axes and one measured value is three columns of a million points, although the axes hold 2000 different numbers. For
display, ``compact_grid`` keeps

* each axis column as a ``GridAxis``: its unique values only (it builds the points asked for when sliced), and
* each measured column as the value matrix in 32-bit floats (the screen cannot show more than 7 digits).

Only copies for display are made this way: the database and QCoDeS' own cache are untouched.
"""
import numpy as np

COMPACT_MIN_POINTS = 50_000  # below this, the columns stay as they are: nothing worth saving


class GridAxis:
    """The flat column of a regular grid that holds the values of one axis, kept as the unique values of that axis.
    Slices (and the whole column, on demand) are built when asked for: ``axis[a:b]`` is an ordinary float array."""

    ndim = 1
    dtype = np.dtype(float)

    def __init__(self, values, shape, axis):
        self._values = np.asarray(values, dtype=float)
        self._size = int(np.prod(shape))
        self._stride = int(np.prod(shape[axis + 1:]))  # grid points per step along this axis

    def __len__(self):
        return self._size

    @property
    def shape(self):
        return (self._size,)

    @property
    def size(self):
        return self._size

    @property
    def nbytes(self):
        return self._values.nbytes

    def _take(self, index):
        return self._values[(index // self._stride) % len(self._values)]

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self._take(np.arange(*key.indices(self._size)))
        return float(self._take(np.asarray(key if key >= 0 else key + self._size)))

    @property
    def real(self):
        return self[:]

    def __array__(self, dtype=None, copy=None):
        whole = self[:]
        return whole if dtype is None else whole.astype(dtype, copy=False)


def _axis_of(values):
    """The axis of a grid-shaped array along which it varies alone (every point equal to the one with the same index along
    that axis and index 0 elsewhere), as GridAxis arguments, or None (a snake axis, an incomplete grid)."""
    for axis in range(values.ndim):
        index = [0] * values.ndim
        index[axis] = slice(None)
        unique = values[tuple(index)]
        shape = [1] * values.ndim
        shape[axis] = -1
        if np.array_equal(values, np.broadcast_to(unique.reshape(shape), values.shape)):
            return unique, axis
    return None


def compact_grid(columns, dependents):
    """{name: flat array or GridAxis} for the grid-shaped ``columns`` ({name: ndarray as QCoDeS gives them}): the axes
    (names not in ``dependents``) as ``GridAxis``, the measured columns as 32-bit flat arrays. A column that is not a
    grid, or not a regular one, is just flattened. Small grids are left in full precision."""
    big = max((c.size for c in columns.values()), default=0) >= COMPACT_MIN_POINTS
    out = {}
    for name, values in columns.items():
        values = np.asarray(values)
        if big and name in dependents:
            kind = np.complex64 if np.iscomplexobj(values) else np.float32
            out[name] = values.astype(kind).ravel()
            continue
        found = _axis_of(values) if big and values.ndim >= 2 and name not in dependents else None
        out[name] = GridAxis(found[0], values.shape, found[1]) if found else \
            values.astype(complex if np.iscomplexobj(values) else float).ravel()
    return out
