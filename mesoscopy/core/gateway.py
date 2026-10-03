"""The instrument gateway: every access to the hardware goes through it (no widgets).

Two threads must not talk to one instrument at the same time (a GPIB bus, a serial line or a socket
cannot interleave two conversations). Instead of each tab keeping its own thread and guessing whether
a measurement is running, tabs submit their instrument calls here, naming the instruments they touch.

* Jobs on different instruments run in parallel; jobs on the same instrument run one after the other.
* A job has a kind that decides what happens when it meets a job on the same instrument:

  =============  ====================================================================================
  ``BACKGROUND`` periodic reads (health check, monitor): skipped, they come back at the next tick
  ``USER``       something the user asked for (read, set, raw command): waits its turn, but is refused
                 while a measurement runs
  ``RUN``        a measurement: waits for background reads, is refused if a user job or another
                 measurement is under way (it never starts unannounced behind a long ramp)
  =============  ====================================================================================

* A refused job is not created: ``submit`` returns None and ``last_refusal`` says why.

A job is a ``Worker``: its ``signals`` (result, error, finished) are delivered in the GUI thread.
"""
import sys
import threading
import traceback
from collections import deque

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from mesoscopy.core.worker import WorkerSignals

BACKGROUND, USER, RUN = "background", "user", "run"
MAX_THREADS = 16  # a job that waits for its turn holds a thread


def parameter_instruments(parameter, _seen=None):
    """Names of the instruments a parameter talks to when read or set.

    An experiment parameter at the root of the station is a delegate (its source's instrument) or a derived
    parameter (the instruments of the parameters it is computed from).
    """
    seen = _seen if _seen is not None else set()
    if id(parameter) in seen:
        return set()
    seen.add(id(parameter))
    names = set()
    source = getattr(parameter, "source", None)
    if source is not None:
        names |= parameter_instruments(source, seen)
    for dependency in getattr(parameter, "_dependencies", {}).values():
        names |= parameter_instruments(dependency, seen)
    root = getattr(parameter, "root_instrument", None)
    if root is not None:
        names.add(root.name)
    return names


def _overlap(a, b):
    """Instrument sets overlap; None means every instrument."""
    return a is None or b is None or bool(a & b)


class Job(QRunnable):
    """One call to the instruments, run in a worker thread once the jobs it has to wait for are done."""

    def __init__(self, gateway, fn, args, kind, instruments, label, waits_for):
        super().__init__()
        self.gateway = gateway
        self.fn, self.args = fn, args
        self.kind, self.instruments, self.label = kind, instruments, label
        self.waits_for = waits_for
        self.signals = WorkerSignals()  # created here, in the GUI thread: its signals reach the GUI thread
        self.done = threading.Event()
        self._started = False

    def start(self):
        """Hand the job to the gateway's threads (once; only needed for ``submit(..., autostart=False)``)."""
        with self.gateway._lock:
            if self._started:
                return
            self._started = True
        self.gateway._pool.start(self)

    def run(self):
        result, error = None, None
        try:
            for job in self.waits_for:
                job.done.wait()
            try:
                result = self.fn(*self.args)
            except BaseException:
                traceback.print_exc()
                exc_type, value = sys.exc_info()[:2]
                error = (exc_type, value, traceback.format_exc())
        finally:
            self.gateway._release(self)  # before the signals: a slot that looks at the gateway sees it free
        if error is not None:
            self.signals.error.emit(error)
        else:
            self.signals.result.emit(result)
        self.signals.finished.emit()


class InstrumentGateway(QObject):
    """Serialises the access to each instrument. See the module documentation."""

    changed = pyqtSignal()  # the set of jobs changed (emitted from any thread; delivered in the GUI thread)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._jobs = []                   # registered jobs: waiting or running
        self._recent = deque(maxlen=64)   # keeps finished jobs (and their signals) alive until delivered
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_THREADS)
        self.last_refusal = ""

    # ----- submitting -----
    def submit(self, fn, *args, kind=USER, instruments=None, label="", autostart=True):
        """Run ``fn(*args)`` in a worker thread once the instruments it touches are free.

        ``instruments``: names of the instruments the call touches (None: all of them).
        Returns the job (connect to ``job.signals``), or None when it was refused or skipped
        (``last_refusal`` holds the reason of a refusal). The job starts when control returns to the
        event loop, so the caller can connect to ``job.signals`` first without missing a result. With
        ``autostart=False`` the job is registered, so that others see the instruments as taken, but
        only starts on ``job.start()``.
        """
        names = None if instruments is None else frozenset(instruments)
        with self._lock:
            conflicts = [j for j in self._jobs if _overlap(j.instruments, names)]
            if conflicts:
                if kind == BACKGROUND:
                    return None
                blocking = [j for j in conflicts
                            if (kind == USER and j.kind == RUN) or (kind == RUN and j.kind in (USER, RUN))]
                if blocking:
                    self.last_refusal = f"{blocking[0].label or 'Another operation'} is using the instruments."
                    return None
            job = Job(self, fn, args, kind, names, label, conflicts)
            self._jobs.append(job)
        self.changed.emit()
        if autostart:
            QTimer.singleShot(0, job.start)
        return job

    def _release(self, job):
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)
            self._recent.append(job)
        job.done.set()
        self.changed.emit()

    # ----- questions -----
    def _conflicting(self, instruments, kinds):
        names = None if instruments is None else frozenset(instruments)
        with self._lock:
            return [j for j in self._jobs if j.kind in kinds and _overlap(j.instruments, names)]

    def run_active(self):
        """A measurement is queued or running."""
        return bool(self._conflicting(None, (RUN,)))

    def busy(self, instruments=None, kinds=(USER, RUN)):
        """Jobs of these kinds are queued or running on (any of) these instruments (None: any instrument)."""
        return bool(self._conflicting(instruments, kinds))

    def reason(self, instruments=None, kinds=(USER, RUN)):
        """Label of the first job busy on these instruments ('' when none)."""
        jobs = self._conflicting(instruments, kinds)
        return (jobs[0].label or "Another operation") + " is using the instruments." if jobs else ""

    def labels(self, kinds=(USER, RUN)):
        """Labels of the registered jobs of these kinds (what the status bar shows)."""
        with self._lock:
            return [j.label for j in self._jobs if j.kind in kinds and j.label]

    def wait_until_free(self, instruments, timeout_s=5.0):
        """Block until the jobs on these instruments are done (a short background read, before closing an
        instrument). Returns False if that took longer than ``timeout_s``."""
        jobs = self._conflicting(instruments, (BACKGROUND, USER, RUN))
        for job in jobs:
            job.start()  # one that was submitted a moment ago has not started yet
        return all(job.done.wait(timeout_s) for job in jobs)

    def shutdown(self, timeout_ms=5000):
        """Wait for the running jobs (the caller should have stopped the measurement)."""
        return self._pool.waitForDone(timeout_ms)
