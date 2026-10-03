"""Snake sweeps for ``dond`` (no Qt).

``dond`` builds all the setpoints of the nested sweeps before it starts (the product of the axes), so the inner axis
cannot simply run backwards on every other pass. A snake axis is therefore swept by *index* (0 ... n-1) through a
``SnakeParameter``: a stand-in with the name, label and unit of the real parameter that turns the index into the
value of the pass: forward on even passes, backward on odd ones, and sets the real parameter (with its limits and
ramp rate). The stand-in answers ``get`` with the value it set, and the sweep stores that after each set
(``get_after_set``): the dataset holds the real values, in snake order.
"""
import numpy as np
from qcodes.dataset import ArraySweep, TogetherSweep
from qcodes.parameters import Parameter


class SnakeParameter(Parameter):
    """Sweeps ``values`` of ``real`` forward on even passes and backward on odd ones. It is set with an index."""

    def __init__(self, real, values):
        values = np.asarray(values, dtype=float)
        state = {"pass": -1, "actual": float(values[0])}
        self._state = state

        def write(index):
            position = int(round(float(index)))
            if position == 0:  # the first point of the inner axis: a new pass starts
                state["pass"] += 1
            if state["pass"] % 2 == 1:
                position = len(values) - 1 - position
            state["actual"] = float(values[position])
            real.set(state["actual"])

        super().__init__(real.name, label=real.label or real.name, unit=real.unit, set_cmd=write,
                         get_cmd=lambda: state["actual"])
        self.real = real
        self.values = values  # what the real parameter is set to, forward

    def reset(self):
        """Start the next sweep forward."""
        self._state["pass"] = -1


def _snake_of(sweep):
    """An index sweep driving a SnakeParameter that does what the sweep ``sweep`` would do, back and forth."""
    values = sweep.get_setpoints()
    stand_in = SnakeParameter(sweep.param, values)
    return ArraySweep(stand_in, np.arange(len(values), dtype=float), sweep.delay, post_actions=sweep.post_actions,
                      get_after_set=True)


def make_snake(sweep):
    """The sweep (a single sweep or a TogetherSweep) as a snake: every other pass runs backwards."""
    if isinstance(sweep, TogetherSweep):
        return TogetherSweep(*[_snake_of(s) for s in sweep.sweeps])
    return _snake_of(sweep)


def real_parameter(parameter):
    """The parameter a sweep really acts on: the one behind a snake stand-in, else the parameter itself."""
    return getattr(parameter, "real", parameter)


def reset_snake(sweeps):
    """Make the snake axes among ``sweeps`` start forward again (before every repetition)."""
    for sweep in sweeps:
        for sub in getattr(sweep, "sweeps", [sweep]):
            if isinstance(sub.param, SnakeParameter):
                sub.param.reset()
