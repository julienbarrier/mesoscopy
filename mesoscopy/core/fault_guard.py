"""Retry an instrument call that failed because the instrument did not answer (no Qt).

A measurement of hours should not be lost to one VISA timeout. While it runs, ``guard`` replaces the ``get`` and
``set`` of the parameters that really talk to an instrument by versions that, when the call fails with a
communication error (a timeout, a lost connection, a serial or VISA error), wait, try to clear the instrument's
buffer and call again, a few times, before the error goes on. Errors that are not about communication (a value
refused by a validator, a bug in a driver) are never retried. ``stop`` (an Event) ends a wait at once.
"""
import functools
import logging
import threading
from contextlib import contextmanager

log = logging.getLogger("mesoscopy.faults")

# exception types of the libraries instruments are driven with, by name (they are not all installed everywhere)
COMMUNICATION_NAMES = {"VisaIOError", "SerialException", "SerialTimeoutException", "ConnectionResetError",
                       "BrokenPipeError", "ZIConnectionException", "ZIAPIException", "ConnectionException"}


def is_communication_error(error):
    """True for an error that says the instrument did not answer, rather than that the request was wrong."""
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return any(cls.__name__ in COMMUNICATION_NAMES for cls in type(error).__mro__) or (
        isinstance(error, OSError) and not isinstance(error, (FileNotFoundError, PermissionError)))


def leaf_parameters(parameter, _seen=None):
    """The parameters that talk to an instrument behind ``parameter``: itself, or what a delegate or a derived
    parameter is made from. Retrying only these, once, avoids retrying a retry."""
    seen = _seen if _seen is not None else set()
    if id(parameter) in seen:
        return []
    seen.add(id(parameter))
    inner = []
    source = getattr(parameter, "source", None)
    if source is not None:
        inner += leaf_parameters(source, seen)
    for dependency in getattr(parameter, "_dependencies", {}).values():
        inner += leaf_parameters(dependency, seen)
    return inner or [parameter]


def clear_instrument(parameter):
    """Best effort to get an instrument that stopped answering back in step: flush its VISA buffer."""
    handle = getattr(getattr(parameter, "root_instrument", None), "visa_handle", None)
    if handle is not None:
        try:
            handle.clear()
        except Exception:
            pass


class RetryGuard:
    """Retries communication errors of the guarded parameters.

    ``announce(text)`` is told what is going on (the status bar); ``pause()`` / ``resume()`` stop and restart the run
    clocks while one or more calls wait."""

    def __init__(self, attempts, wait_s, stop, announce=None, pause=None, resume=None, sleep=None):
        self.attempts, self.wait_s, self.stop = attempts, wait_s, stop
        self.announce = announce or (lambda text: None)
        self._pause, self._resume = pause or (lambda: None), resume or (lambda: None)
        self._sleep = sleep or (lambda seconds: self.stop.wait(seconds))  # True when stopped
        self._lock = threading.Lock()
        self._waiting = 0
        self.retries = 0  # how many retries were made (for the report)

    def _enter_wait(self):
        with self._lock:
            self._waiting += 1
            if self._waiting == 1:
                self._pause()

    def _leave_wait(self):
        with self._lock:
            self._waiting -= 1
            if self._waiting == 0:
                self._resume()

    def _wrap(self, parameter, call, what):
        @functools.wraps(call)
        def retrying(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return call(*args, **kwargs)
                except Exception as error:
                    if attempt >= self.attempts or self.stop.is_set() or not is_communication_error(error):
                        raise
                    attempt += 1
                    wait = self.wait_s * attempt
                    text = (f"{parameter.full_name} did not answer ({type(error).__name__}): retry {attempt} of "
                            f"{self.attempts} in {wait:g} s. Stop ends the wait.")
                    log.warning(text)
                    self.announce(text)
                    self.retries += 1
                    self._enter_wait()
                    try:
                        clear_instrument(parameter)
                        if self._sleep(wait):  # Stop was pressed
                            raise error
                    finally:
                        self._leave_wait()
        return retrying

    @contextmanager
    def guard(self, parameters):
        """Within the block the ``get`` and ``set`` of the instrument parameters behind ``parameters`` retry."""
        if self.attempts <= 0:
            yield
            return
        replaced = []  # (parameter, attribute, original instance attribute or None)
        leaves = []
        for parameter in parameters:
            for leaf in leaf_parameters(parameter):
                if all(leaf is not other for other in leaves):
                    leaves.append(leaf)
        try:
            for leaf in leaves:
                for attribute, usable in (("get", leaf.gettable), ("set", leaf.settable)):
                    if not usable or not callable(getattr(leaf, attribute, None)):
                        continue
                    original = vars(leaf).get(attribute)
                    setattr(leaf, attribute, self._wrap(leaf, getattr(leaf, attribute), attribute))
                    replaced.append((leaf, attribute, original))
            yield
        finally:
            for leaf, attribute, original in replaced:
                if original is not None:
                    setattr(leaf, attribute, original)
                else:
                    vars(leaf).pop(attribute, None)
