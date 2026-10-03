"""Small helpers for drawing time traces (no Qt)."""
import math


def nice_step(span, max_ticks=6):
    """A round tick step giving at most ``max_ticks`` ticks over ``span``.

    A step that divides the span exactly is preferred, so the axis starts on a tick (-24, -18 ... 0);
    the rounder steps (1, 2, 2.5, 5, 10) are tried before 3, 4 and 6.
    """
    raw = span / (max_ticks - 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factors in ((1, 2, 2.5, 5, 10), (3, 4, 6)):
        for factor in factors:
            step = factor * magnitude
            if step >= raw * (1 - 1e-9) and abs(span / step - round(span / step)) < 1e-6:
                return step
    return next(f * magnitude for f in (1, 2, 2.5, 5, 10) if f * magnitude >= raw * (1 - 1e-9))


def decimate(points, buckets):
    """Keep the minimum and the maximum of each of ``buckets`` equal slices of the time range, so a very
    long series is drawn quickly and its peaks stay visible. ``points`` = [(x fraction 0..1, value)]."""
    if len(points) <= 4 * buckets:
        return points
    kept = {}
    for index, (fraction, value) in enumerate(points):
        bucket = min(int(fraction * buckets), buckets - 1)
        low, high = kept.get(bucket, (None, None))
        if low is None or value < points[low][1]:
            low = index
        if high is None or value > points[high][1]:
            high = index
        kept[bucket] = (low, high)
    indices = sorted({i for pair in kept.values() for i in pair})
    return [points[i] for i in indices]


def derivative(x, y):
    """dy/dx of a curve, point by point (central differences, one-sided at the ends, for any spacing of x).

    Points that are not finite are left out of the calculation and come back as NaN, and so does the slope where two
    neighbouring x values are equal (a sweep that turns around, a snake): the curve shows a gap there instead of a
    wild value. Returns an array of the length of ``y``."""
    import numpy as np
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    result = np.full(y.shape, np.nan)
    good = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if len(good) < 2:
        return result
    xs, ys = x[good], y[good]
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.gradient(ys, xs)
    slope[~np.isfinite(slope)] = np.nan
    result[good] = slope
    return result
