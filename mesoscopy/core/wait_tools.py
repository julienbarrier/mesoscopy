"""Waiting for an instrument to reach a state: the helpers of the actions and of the queue steps.

Available in every action as ``wait``, ``wait_until``, ``wait_below``, ``wait_above`` and ``wait_stable``, and used by
the "wait" steps of the queue. Unlike ``time.sleep`` and a ``while`` loop of your own, they

* end at once when Stop is pressed (``WaitInterrupted``),
* give up after ``timeout`` seconds (``WaitTimeout``, which fails the run: better than waiting for ever),
* say in the status bar what they wait for, and the current value,
* leave the clocks of the run standing still while they wait (the estimated remaining time stays right).

This module needs nothing but the standard library: "Export as Python" copies it into the script, where the same
calls work (a Stop does not exist there, Ctrl+C does).
"""
import time

ANNOUNCE_EVERY_S = 5.0
SLICE_S = 0.2      # a wait is cut in slices of this length, to notice a Stop quickly


class WaitInterrupted(Exception):
    """Stop was pressed while waiting."""


class WaitTimeout(RuntimeError):
    """What was waited for did not happen within the timeout."""


def _duration(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


class WaitTools:
    """``stopped()`` says whether to give up; ``announce(text)`` shows progress; ``pause()`` / ``resume()`` stop and restart
    the clocks of the run around a wait."""

    def __init__(self, stopped=None, announce=None, pause=None, resume=None, clock=time.monotonic, sleep=time.sleep):
        self._stopped = stopped or (lambda: False)
        self._announce = announce or (lambda text: None)
        self._pause, self._resume = pause or (lambda: None), resume or (lambda: None)
        self._clock, self._sleep = clock, sleep

    # ----- the loop every wait uses -----
    def _loop(self, check, timeout, poll, what):
        """Call ``check()`` -> (done, status text) every ``poll`` seconds until done, the timeout or a Stop."""
        start, last_announced = self._clock(), None
        self._pause()
        try:
            while True:
                if self._stopped():
                    raise WaitInterrupted(f"stopped while waiting for {what}")
                done, status = check()
                elapsed = self._clock() - start
                if done:
                    return elapsed
                if timeout is not None and elapsed >= timeout:
                    raise WaitTimeout(f"{what} not reached after {_duration(elapsed)}" + (f" ({status})" if status else ""))
                if last_announced is None or self._clock() - last_announced >= ANNOUNCE_EVERY_S:
                    last_announced = self._clock()
                    self._announce(f"Waiting for {what}" + (f": {status}" if status else "") + f" ({_duration(elapsed)})")
                remaining = poll if timeout is None else min(poll, max(timeout - elapsed, 0.0))
                self._nap(remaining)
        finally:
            self._resume()

    def _nap(self, seconds):
        end = self._clock() + seconds
        while not self._stopped():
            left = end - self._clock()
            if left <= 0:
                return
            self._sleep(min(SLICE_S, left))

    # ----- what an action can call -----
    def wait(self, seconds, message=""):
        """Wait ``seconds`` (like time.sleep, but Stop ends it)."""
        end = self._clock() + seconds
        self._loop(lambda: (self._clock() >= end, f"{max(end - self._clock(), 0):.0f} s left"),
                   None, SLICE_S, message or f"{seconds:g} s")

    def wait_until(self, condition, timeout=None, poll=1.0, message="the condition"):
        """Wait until ``condition()`` is true, e.g. ``wait_until(lambda: vtop() > 0.1, timeout=600)``."""
        return self._loop(lambda: (bool(condition()), ""), timeout, poll, message)

    def wait_below(self, parameter, value, timeout=None, poll=1.0):
        """Wait until the parameter reads below ``value``."""
        return self._loop(lambda: self._compare(parameter, value, lambda v: v < value, "<"), timeout, poll,
                          f"{_name(parameter)} < {value:g}")

    def wait_above(self, parameter, value, timeout=None, poll=1.0):
        """Wait until the parameter reads above ``value``."""
        return self._loop(lambda: self._compare(parameter, value, lambda v: v > value, ">"), timeout, poll,
                          f"{_name(parameter)} > {value:g}")

    @staticmethod
    def _compare(parameter, value, test, symbol):
        reading = float(parameter())
        return test(reading), f"{reading:.6g}, need {symbol} {value:g}"

    def wait_stable(self, parameter, tol, dwell, target=None, timeout=None, poll=1.0):
        """Wait until the parameter stays within ``tol`` for ``dwell`` seconds: all the readings within +-tol of ``target``
        (when given), or, without a target, spread over no more than 2*tol (a drift or a ripple that small)."""
        streak = []  # (time, reading) since the readings last left the band

        def check():
            now, reading = self._clock(), float(parameter())
            streak.append((now, reading))
            if target is not None and abs(reading - target) > tol:
                del streak[:]
            elif max(r for _, r in streak) - min(r for _, r in streak) > 2 * tol:
                del streak[:-1]  # restart from this reading (the older ones are too far from it)
                while len(streak) > 1 and abs(streak[-1][1] - streak[0][1]) > 2 * tol:
                    del streak[0]
            held = now - streak[0][0] if streak else 0.0
            return bool(streak) and held >= dwell, (f"{reading:.6g}, within +-{tol:g}"
                                                    + (f" of {target:g}" if target is not None else "")
                                                    + f" for {held:.0f} of {dwell:g} s")
        what = f"{_name(parameter)} stable to +-{tol:g}" + (f" around {target:g}" if target is not None else "")
        return self._loop(check, timeout, poll, what)

    def functions(self):
        """The helpers by name, to put in the namespace of the actions."""
        return {name: getattr(self, name) for name in ("wait", "wait_until", "wait_below", "wait_above", "wait_stable")}


def _name(parameter):
    return getattr(parameter, "name", None) or getattr(parameter, "full_name", None) or "value"


WAIT_NAMES = ("wait", "wait_until", "wait_below", "wait_above", "wait_stable")
