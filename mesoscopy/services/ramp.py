"""Bringing experiment parameters to 0 at their maximum ramp rate (no widgets besides the progress dialog).

An experiment parameter (the Parameter explorer) carries its safe limits and its maximum ramp rate as the ``step``
and ``inter_delay`` of its QCoDeS parameter, so setting it to 0 ramps it at that rate. Each parameter is ramped by a
job of the instrument gateway: parameters of different instruments ramp together, those of one instrument take turns.
"""
from PyQt6.QtCore import QEventLoop, QObject, Qt
from PyQt6.QtWidgets import QProgressDialog

from mesoscopy.core.gateway import USER, parameter_instruments
from mesoscopy.core.parameter_io import cached_value


def _ramp_to_zero(parameter, history=None):
    """Set the parameter to 0 (a ramp when it has a step and an inter-delay: they come from its maximum ramp rate).
    With a ``history`` the value it had is remembered, so that it can be restored."""
    if history is not None:
        history.set(parameter, 0)
    else:
        parameter.set(0)


def _may_be_nonzero(parameter):
    """False only when the last known value is a number equal to 0 (nothing to ramp)."""
    value = cached_value(parameter)
    try:
        return value is None or float(value) != 0.0
    except (TypeError, ValueError):
        return True


class _Batch(QObject):
    """The ramp jobs of one request: counts them down and reports the problems when the last one ended."""

    def __init__(self, problems, on_finished):
        super().__init__()
        self.problems = problems
        self.on_finished = on_finished
        self.left = 0

    def job_failed(self, parameter, error):
        self.problems.append(f"{parameter.full_name}: {type(error[1]).__name__}: {error[1]}")

    def job_done(self):
        self.left -= 1
        if self.left <= 0 and self.on_finished:
            self.on_finished(self.problems)


class RampService(QObject):
    def __init__(self, services):
        super().__init__()
        self.services = services
        self._batches = []  # keeps the batches (and their signal receivers) alive until they are done

    def settable_parameters(self, instrument_names=None, changed_only=False):
        """The experiment parameters that can be set (instrument parameters, not derived or station ones), on any of
        the named instruments, or on all the connected ones when ``instrument_names`` is None.

        ``changed_only``: only those the application has set (in the Parameter explorer, or by a sweep) and that are
        not at 0 already: there is no reason to ramp what was never changed. This is what is brought to 0 before the
        instruments are closed, and after a measurement failed."""
        registry = self.services.registry
        history = self.services.restore
        wanted = None if instrument_names is None else set(instrument_names)
        found = []
        for name, parameter in registry.parameters().items():
            definition = registry.definitions.get(name)
            if definition is None or definition.kind != "instrument" or not parameter.settable:
                continue
            if wanted is not None and not parameter_instruments(parameter) & wanted:
                continue
            if changed_only and not (history.was_touched(parameter) and _may_be_nonzero(parameter)):
                continue
            found.append(parameter)
        return found

    def start(self, parameters, on_finished=None, history=None):
        """Ramp the parameters to 0, each in its own gateway job. ``on_finished(problems)`` is called, in the GUI
        thread, once every job has ended (at once when none could start). Returns the number of jobs started.
        ``history`` (a RestoreHistory) remembers the values the parameters had."""
        gateway = self.services.gateway
        problems = []
        batch = _Batch(problems, None)
        for parameter in parameters:
            if parameter.step is None:  # no maximum ramp rate: QCoDeS sets the value in one go
                problems.append(f"{parameter.full_name} has no maximum ramp rate: set to 0 directly")
            job = gateway.submit(
                _ramp_to_zero, parameter, history, kind=USER, instruments=parameter_instruments(parameter),
                label=f"Ramping {parameter.full_name} to 0",
            )
            if job is None:
                problems.append(f"{parameter.full_name}: {gateway.last_refusal}")
                continue
            batch.left += 1
            job.signals.error.connect(lambda err, p=parameter: batch.job_failed(p, err))
            job.signals.finished.connect(batch.job_done)
        if batch.left == 0:
            if on_finished:
                on_finished(problems)
            return 0

        def finished(all_problems):
            self._batches.remove(batch)
            if on_finished:
                on_finished(all_problems)

        batch.on_finished = finished
        self._batches.append(batch)
        return batch.left

    def ramp_and_wait(self, parameters, parent=None, title="Ramping to 0"):
        """Ramp the parameters to 0 and wait for it (the window stays responsive, a dialog says what is going on).
        Returns the problems. Used before instruments are closed: there is no way to skip it, a ramp ends by itself."""
        if not parameters:
            return []
        loop, outcome = QEventLoop(), {}

        def finished(problems):
            outcome["problems"] = problems
            loop.quit()

        started = self.start(parameters, finished)
        if started == 0:  # nothing could start: the problems are known already
            return outcome.get("problems", [])
        dialog = QProgressDialog(f"{title}: {started} parameter(s)...", None, 0, 0, parent)  # no cancel button
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()
        if "problems" not in outcome:  # a job that ended already has quit the loop before it started
            loop.exec()
        dialog.close()
        return outcome.get("problems", [])
