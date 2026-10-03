"""Sweeps run backwards (no Qt), for a measurement that goes back and forth on every repetition."""
import numpy as np
from qcodes.dataset import ArraySweep, TogetherSweep


def _reversed(sweep):
    """The sweep that visits the same values in the opposite order (same delay, actions and read-back)."""
    return ArraySweep(sweep.param, np.asarray(sweep.get_setpoints(), dtype=float)[::-1], sweep.delay,
                      post_actions=sweep.post_actions, get_after_set=sweep.get_after_set)


def reverse_sweep(sweep):
    """The sweep (a single sweep or a TogetherSweep) from its last value to its first."""
    if isinstance(sweep, TogetherSweep):
        return TogetherSweep(*[_reversed(s) for s in sweep.sweeps])
    return _reversed(sweep)
