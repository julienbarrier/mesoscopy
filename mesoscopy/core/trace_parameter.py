"""Traces: parameters that give an array together with its axis (no Qt).

QCoDeS stores such a result with a ``ParameterWithSetpoints``: the parameter, and the parameter(s) that give the
axis. Two sources feed the application with them:

* a driver that defines a ``ParameterWithSetpoints`` (a spectrum analyser, a scope): it is measured as it is;
* ``TraceParameter``: any parameter that returns an array (a lock-in scope or spectrum node, for example) given an
  axis, so that it can be measured the same way.
"""
import numpy as np
from qcodes.parameters import Parameter, ParameterWithSetpoints
from qcodes.validators import Arrays


def is_trace(parameter):
    """True for a parameter that has setpoints: its value is an array stored with its axis."""
    return isinstance(parameter, ParameterWithSetpoints)


def trace_axis_names(parameter):
    return [sp.name for sp in getattr(parameter, "setpoints", ())]


def trace_points(parameter):
    """Number of points of a trace, or None when it cannot be told without talking to the instrument."""
    try:
        return int(parameter.vals.shape[0])
    except Exception:
        return None


class AxisParameter(Parameter):
    """The axis of a trace: a fixed linspace, or the values of another array parameter read at each acquisition."""

    def __init__(self, name, label, unit, start=0.0, stop=1.0, points=101, source=None):
        self.axis_source = source  # None: the linspace; else the parameter that gives the axis
        self._linspace = np.linspace(start, stop, int(points)) if source is None else None
        super().__init__(
            name, label=label or name, unit=unit, get_cmd=self._values, vals=Arrays(shape=(self._length,),),
            snapshot_get=False, snapshot_value=False,
        )

    def _values(self):
        if self.axis_source is None:
            return self._linspace
        return np.asarray(self.axis_source.get(), dtype=float)

    def _length(self):
        return len(self._linspace) if self.axis_source is None else len(np.atleast_1d(self._values()))


class TraceParameter(ParameterWithSetpoints):
    """An array-valued parameter ``source`` measured as a trace over ``axis`` (an ``AxisParameter``).

    It keeps ``source`` (and the axis source) as dependencies, so that the instrument gateway reserves the right
    instruments for it, and never takes part in a snapshot (reading it would acquire a trace)."""

    def __init__(self, name, source, axis, label="", unit=""):
        super().__init__(
            name, setpoints=[axis], vals=Arrays(shape=(axis._length,)), label=label or name,
            unit=unit or getattr(source, "unit", ""), get_cmd=lambda: np.asarray(source.get(), dtype=float),
        )
        self.source = source
        self._dependencies = {"source": source}
        if axis.axis_source is not None:
            self._dependencies["axis"] = axis.axis_source
