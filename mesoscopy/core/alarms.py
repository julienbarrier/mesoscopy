"""Alarm limits of a parameter (no Qt): where an alarm goes off, from the values the parameter allows.

The allowed values are the range of the parameter's validator (the safe limits of an experiment parameter, the limits of
a station-file parameter, a driver's own range). The alarm goes off when the value reaches ``percent`` of the allowed
maximum on the positive side, or of the allowed minimum on the negative side. For a range that is symmetric about 0
this is |value| >= percent of the limit; for another range each side has its own limit, and a side that has no limit (or
that is on the other side of 0) is not watched.
"""
import math

HIGH, LOW = "high", "low"
REARM_FRACTION = 0.01  # once above a limit, the value must come back 1 % of that limit inside it to re-arm the alarm


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def allowed_range(parameter):
    """(minimum, maximum) the parameter allows; None for a side without a limit. (None, None): no limits at all."""
    validator = getattr(parameter, "vals", None)
    candidates = [validator, *getattr(validator, "_validators", [])]  # a MultiType holds several validators
    for candidate in candidates:
        low, high = _finite(getattr(candidate, "_min_value", None)), _finite(getattr(candidate, "_max_value", None))
        if low is not None or high is not None:
            return low, high
    return None, None


def thresholds(parameter, percent):
    """(low threshold, high threshold) of the alarm; None for a side that is not watched."""
    low, high = allowed_range(parameter)
    fraction = percent / 100.0
    return (fraction * low if low is not None and low < 0 else None,
            fraction * high if high is not None and high > 0 else None)


def has_limits(parameter):
    low, high = thresholds(parameter, 100)
    return low is not None or high is not None


def side_of(value, limits):
    """HIGH or LOW when ``value`` is at or beyond a threshold of ``limits`` = (low, high), else None."""
    low, high = limits
    if high is not None and value >= high:
        return HIGH
    if low is not None and value <= low:
        return LOW
    return None


def rearmed(value, side, limits):
    """True once ``value`` is back inside the threshold of ``side`` (by a small margin, so that a value hovering at the
    limit does not raise the alarm again and again)."""
    threshold = limits[1] if side == HIGH else limits[0]
    if threshold is None:
        return True
    margin = REARM_FRACTION * abs(threshold)
    return value < threshold - margin if side == HIGH else value > threshold + margin


def describe_limit(parameter, side, percent, threshold):
    low, high = allowed_range(parameter)
    allowed = high if side == HIGH else low
    unit = f" {parameter.unit}" if getattr(parameter, "unit", "") else ""
    return f"{percent:g} % of {allowed:g}{unit} = {threshold:g}{unit}"
