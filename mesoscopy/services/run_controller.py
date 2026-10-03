"""The run controller: runs a measurement through QCoDeS ``dond`` and tells everyone how it goes (no widgets).

The Measurement tab builds a ``RunRequest`` from its fields and hands it to ``RunController.start``. The controller
runs it in the instrument gateway (one job that holds every instrument), and publishes what happens as signals that
the tabs subscribe to: the state of the run, its start and its end, the run being written, the repetition. It never
touches a widget.
"""
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import qcodes
from PyQt6.QtCore import QObject, pyqtSignal
from qcodes.dataset import dond, load_by_id
from qcodes.parameters import DelegateParameter

from mesoscopy.core.auto_actions import export_settings, save_dataset_plots
from mesoscopy.core.dond_options import DondOptions, run_names
from mesoscopy.core.dry_run import check_request
from mesoscopy.core.experiment_parameters import BreakoutWatcher
from mesoscopy.core.fault_guard import RetryGuard
from mesoscopy.core.gateway import RUN
from mesoscopy.core.live_data import next_run_id
from mesoscopy.core.live_feed import capture_live_runs
from mesoscopy.core.parameter_io import latest_for_monitor, read_for_monitor, source_chain_ids
from mesoscopy.core.qcodes_options import effective_use_threads
from mesoscopy.core.run_progress import RunProgress
from mesoscopy.core.run_setup import build_setup, record_setup
from mesoscopy.core.wait_tools import WaitTools
from mesoscopy.core.trace_parameter import is_trace
from mesoscopy.experiment.reverse import reverse_sweep
from mesoscopy.experiment.snake import real_parameter, reset_snake

# dond flushes the data to the database at this period (seconds); the live plot reads from there
WRITE_PERIOD = 0.5

# states of the run: idle, running, pausing (a pause was asked and is waiting for the current point), paused,
# stopping, stopping_ramp (stopping, and the swept parameters will be ramped to 0 afterwards)
IDLE, RUNNING, PAUSING, PAUSED, STOPPING, STOPPING_RAMP = (
    "idle", "running", "pausing", "paused", "stopping", "stopping_ramp"
)


@dataclass
class RunRequest:
    """Everything the Measurement tab asks for. The sweeps are in the order of ``dond``: the first is the outermost
    loop (slowest axis), the last the innermost (fastest)."""
    sweeps: list
    measured: list                       # [(alias, parameter)]
    progress: RunProgress                # the sweeps count their points in it
    repeat: int
    experiment_name: str
    measurement_name: str                # "" for the default name made from the sweeps
    breakout: bool                       # stop on the breakout conditions of the experiment parameters
    state: dict                          # the Measurement tab state, recorded in the snapshot of the run
    ramp_when_finished: Callable[[], bool]  # asked when the run ends (the box may be ticked during the run)
    axis_sizes: list = field(default_factory=list)
    options: DondOptions = field(default_factory=DondOptions)  # the advanced settings (dond options)
    back_and_forth: bool = False         # one axis, repeated: every other repetition sweeps backwards


@dataclass
class RunSession:
    """A run that is going on or has ended."""
    request: RunRequest
    db_file: str
    sample_name: str
    measurement_name: str
    progress: RunProgress
    axis_sizes: list
    failed: bool = False
    stopped: bool = False
    reason: str = ""                     # why a breakout condition stopped the run
    run_ids: list = field(default_factory=list)  # the runs written so far (several datasets: several runs each)

    @property
    def experiment_name(self):
        return self.request.experiment_name

    @property
    def dataset_names(self):
        """Names of the datasets of the measurement (empty: a single one)."""
        return self.request.options.dataset_names


def swept_parameters(sweep):
    """Parameters swept together by one dond axis (several for a TogetherSweep). For a snake axis, the real
    parameters, not the stand-ins that sweep them back and forth."""
    return [real_parameter(s.param) for s in getattr(sweep, "sweeps", [sweep])]


def default_measurement_name(sweeps):
    if not sweeps:
        return "Single acquisition"
    return " / ".join(
        f"{type(sweep).__name__} {'+'.join(p.full_name for p in swept_parameters(sweep))}" for sweep in sweeps
    )


class RunController(QObject):
    """Runs the measurement asked for by the Measurement tab. See the module documentation."""

    runStateChanged = pyqtSignal(str)   # one of IDLE ... STOPPING_RAMP
    runStarted = pyqtSignal(object)     # RunSession
    runFinished = pyqtSignal(object)    # RunSession, once the run has ended however it ended
    runIdKnown = pyqtSignal(int)        # id of the run about to be written (emitted from the measurement thread)
    runIdsKnown = pyqtSignal(object)    # the ids of all the datasets about to be written (one per dataset)
    liveRunStarted = pyqtSignal(object)  # LiveRun of a dataset being written (from the measurement thread)
    liveDataChanged = pyqtSignal()      # a LiveRun received rows or ended (from QCoDeS' subscriber thread)
    monitorReadings = pyqtSignal(object)  # readings of the monitored parameters taken by the measurement: [(key, reading, error)]
    repetitionChanged = pyqtSignal(int, int)  # repetition in progress, number of repetitions
    repetitionFinished = pyqtSignal(int, int)  # a repetition (a run of its own) is written: its number, the number of them
    _pausedByRun = pyqtSignal(bool)     # the measurement thread is waiting for Resume (True) / goes on (False)

    def __init__(self, services):
        super().__init__()
        self.services = services
        self.state = IDLE
        self.session = None
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()  # set while the run may go on, cleared by a pause
        self._resume_event.set()
        self._watcher = None
        self._swept = []               # the parameters the running measurement sweeps
        self._ramp_after_stop = False  # "Stop and ramp to 0" was pressed
        self._last_monitor = 0.0       # when the measurement last took the monitored parameters (monotonic seconds)
        self.last_problem = ""         # why the last start was refused (the queue shows it)
        self._pausedByRun.connect(self._on_paused_by_run)
        self.runIdsKnown.connect(self._on_run_ids)
        self.repetitionChanged.connect(self._on_repetition)

    @property
    def running(self):
        return self.state != IDLE

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.runStateChanged.emit(state)

    def wait_tools(self):
        """The waiting helpers of the actions (``wait_until`` ...): they end when Stop is pressed, say what they wait
        for in the status bar and leave the clocks of the run standing still."""
        def progress(method):
            return lambda: getattr(self.session.progress, method)() if self.session is not None else None

        return WaitTools(stopped=lambda: self._stop_event.is_set(), announce=lambda text: self.services.status.show(text, 8000),
                         pause=progress("pause"), resume=progress("resume"))

    # ================= starting =================
    def start(self, request):
        """Run the request with dond (1 to 4 dimensions, repeated ``request.repeat`` times). Returns True if it started."""
        status = self.services.status
        self.last_problem = ""
        if self.running:
            status.show("A measurement is already running.", 3000)
            return False
        if self.services.station.station is None:
            status.show("Please load a station first.", 2000)
            return False
        try:
            db_file = self.services.data.database_for_run()
        except ValueError as e:
            self.last_problem = str(e)
            status.show(str(e), 5000)
            return False
        report = check_request(request, self.services, check_database=False)  # what cannot work is not started
        if not report.ok:
            self.last_problem = "; ".join(report.errors)
            status.show("Cannot start: " + self.last_problem, 10000)
            return False

        sweeps, progress = request.sweeps, request.progress
        sample_name = self.services.data.sample_name
        measurement_name = request.measurement_name or default_measurement_name(sweeps)
        progress.total = math.prod(s.num_points for s in sweeps)  # 1 without sweeps: a single acquisition
        progress.inner_points = sweeps[-1].num_points if sweeps else 1
        progress.x_default = swept_parameters(sweeps[-1])[0].register_name if sweeps else None
        request.axis_sizes = [s.num_points for s in sweeps]
        # breakout: the experiment parameters with a condition are checked after every point
        watcher = None
        if request.breakout:
            watcher = BreakoutWatcher(
                self.services.registry.breakout_items(), [parameter for _, parameter in request.measured],
                mode=self.services.settings.breakout_mode,
            )
        # the measurement takes every instrument (dond also snapshots the whole station): the gateway refuses
        # it while the user is using an instrument, and refuses the user from then on
        job = self.services.gateway.submit(
            self._run_task, db_file, request, sample_name, measurement_name, effective_use_threads(self.services.settings),
            kind=RUN, instruments=None, label=f"Measurement '{measurement_name}'", autostart=False,
        )
        if job is None:
            self.last_problem = self.services.gateway.last_refusal
            status.show(f"Cannot start: {self.services.gateway.last_refusal}", 6000)
            return False

        self.services.data.select_database(db_file)  # the database of the run is the selected one, shown in the Data tab
        self.session = RunSession(request, db_file, sample_name, measurement_name, progress, request.axis_sizes)
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._swept = self._unique(p for sweep in sweeps for p in swept_parameters(sweep))
        for parameter in self._swept:
            self.services.restore.mark_touched(parameter)  # to be brought back to 0 when the application closes
        self._ramp_after_stop = False
        self._watcher = watcher
        self._record_setup(request, sample_name)
        progress.start()
        self._set_state(RUNNING)
        self.runStarted.emit(self.session)  # the tabs lock their inputs and start their clocks

        job.signals.finished.connect(self._on_finished)
        job.signals.error.connect(self._on_error)
        job.start()
        note = self.services.data.last_note
        warnings = report.warnings
        status.show(f"Running {measurement_name}..." + (f" {note}." if note else "")
                    + (f" {len(warnings)} warning(s), see Check setup: {warnings[0]}" if warnings else ""))
        return True

    def _record_setup(self, request, sample_name):
        """Put the current setup (experiment parameter definitions, Measurement tab) in the station metadata.

        QCoDeS adds the station metadata to the snapshot it takes when the run starts, so the snapshot of
        the run holds what was set up at the click on Run, whatever the user changed before. The values of
        the instrument parameters are in the snapshot already: they are cached by QCoDeS when set.
        """
        try:
            setup = build_setup(self.services.registry, request.state, sample_name)
            record_setup(self.services.station.station, setup)
        except Exception as e:  # recording is a convenience: never prevent a measurement
            print(f"Could not record the setup in the snapshot: {e}")

    @staticmethod
    def _unique(parameters):
        """The parameters without repeats, in order."""
        unique = []
        for parameter in parameters:
            if all(parameter is not other for other in unique):
                unique.append(parameter)
        return unique

    # ================= the measurement thread =================
    def _run_task(self, db_file, request, sample_name, measurement_name, use_threads):
        """Measurement-thread task: the measurement, with the reads and sets that fail because an instrument does not
        answer tried again (see ``core.fault_guard``) instead of ending the run at the first timeout."""
        settings, progress = self.services.settings, self.session.progress
        guard = RetryGuard(
            settings.retry_attempts, settings.retry_wait_s, self._stop_event,
            announce=lambda text: self.services.status.show(text, 20000), pause=progress.pause, resume=progress.resume,
        )
        options = request.options
        with guard.guard([*(p for _, p in request.measured), *self._swept]), \
                export_settings(options.export, options.export_type, options.export_path):  # QCoDeS' automatic export
            self._run_repetitions(db_file, request, sample_name, measurement_name, use_threads)

    def _run_repetitions(self, db_file, request, sample_name, measurement_name, use_threads):
        """Run dond over the sweeps, ``request.repeat`` times one after the other.

        The data is not returned: it is written to the database, which the live plot reads. Every repetition is
        a run of its own, named with its number when there are several. Stop, or a breakout condition, ends them all.
        """
        sweeps, repeat = request.sweeps, request.repeat
        qcodes.dataset.initialise_or_create_database_at(db_file)
        exp = qcodes.dataset.load_or_create_experiment(experiment_name=request.experiment_name, sample_name=sample_name)
        parameters = []
        for alias, parameter in request.measured:
            if alias == parameter.full_name or is_trace(parameter):
                parameters.append(parameter)  # a trace keeps its setpoints only if it is not wrapped: no alias for it
            else:  # measured under the user's alias
                parameters.append(DelegateParameter(alias, source=parameter))
        options = request.options
        backwards = [reverse_sweep(s) for s in sweeps] if request.back_and_forth and repeat > 1 else None
        for index in range(repeat):
            if index and (self._stop_event.is_set() or (self._watcher is not None and self._watcher.reason)):
                break
            reset_snake(sweeps)  # a snake axis starts forward in every repetition
            suffix = "" if repeat == 1 else f" [{index + 1}/{repeat}]"
            names = run_names(measurement_name, options, suffix)
            first_id = next_run_id(db_file)
            self.runIdKnown.emit(first_id)
            self.runIdsKnown.emit([first_id + k for k in range(len(names))])
            self.repetitionChanged.emit(index + 1, repeat)
            print(f"Running {names[0]}: {math.prod(s.num_points for s in sweeps)} point(s)")
            this_way = backwards if backwards is not None and index % 2 else sweeps  # the odd repetitions go back
            try:
                with capture_live_runs(self.liveRunStarted.emit, self.liveDataChanged.emit):
                    dond(
                        *this_way, *parameters, exp=exp, measurement_name=names if options.datasets else names[0],
                        do_plot=False, show_progress=False, write_period=options.write_period or WRITE_PERIOD,
                        break_condition=self._break_condition,
                        use_threads=use_threads if options.use_threads is None else options.use_threads,
                        enter_actions=options.enter_actions, exit_actions=options.exit_actions,
                        additional_setpoints=[p for _, p in options.additional_setpoints],
                        dataset_dependencies=self._dataset_dependencies(options, names, this_way, request.measured, parameters),
                        in_memory_cache=options.in_memory_cache, log_info=options.log_info or None,
                    )
            except IndexError:
                # Stop pressed while an enter action waited: QCoDeS ends the run before any dataset exists and then trips
                # over the empty list of datasets. Nothing was measured: it is a stop, not an error.
                if not self._stop_event.is_set():
                    raise
            finally:
                if options.save_plot:
                    self._save_plots(options, first_id, len(names))
            self.repetitionFinished.emit(index + 1, repeat)

    def _save_plots(self, options, first_id, count):
        """Save the plots of the datasets of the run that was just written (``plot_dataset``, next to the exported data).
        What cannot be plotted, or was never written, is skipped: this is a convenience and never fails a run."""
        datasets = []
        for run_id in range(first_id, first_id + count):
            try:
                datasets.append(load_by_id(run_id))
            except Exception:
                continue  # the run failed before its dataset existed
        try:
            written = save_dataset_plots(datasets, options.plot_format)
        except Exception as e:
            print(f"Could not save the plots: {type(e).__name__}: {e}")
            return
        if written:
            self.services.status.show(f"Plot saved: {written[0]}" + (f" (+{len(written) - 1})" if len(written) > 1 else ""), 8000)

    @staticmethod
    def _dataset_dependencies(options, names, sweeps, measured, parameters):
        """dond's ``dataset_dependencies``: for each dataset its setpoints and measured parameters, as the objects dond
        holds (the stand-in of a snake axis, the alias delegate of a measured parameter). None for a single dataset."""
        if not options.datasets:
            return None
        setpoints = {}
        for sweep in sweeps:
            for sub in getattr(sweep, "sweeps", [sweep]):
                setpoints[real_parameter(sub.param).name] = sub.param
        setpoints.update(dict(options.additional_setpoints))
        measured_objects = {alias: parameter for (alias, _), parameter in zip(measured, parameters)}
        return {
            name: [setpoints[n] for n in dataset["setpoints"] if n in setpoints]
            + [measured_objects[n] for n in dataset["measured"] if n in measured_objects]
            for name, dataset in zip(names, options.datasets)
        }

    def _break_condition(self):
        """dond's break condition, asked after every point: the Stop button, a pause, or a breakout condition.

        While paused it waits here, between two points, so that the instruments are left as they are.
        """
        if self._stop_event.is_set():
            return True
        # the alarms on parameters: what this point measured or set is current, the others are read now and then
        request = self.session.request
        raised = self.services.alarms.check_run([*(p for _, p in request.measured), *self._swept])
        for record in raised:
            if record["action"] == "pause":
                self._resume_event.clear()  # paused below, at this very point
        if any(record["action"] in ("stop", "stop_ramp") for record in raised):
            return True  # the alarm's slot marks the run as stopped (and ramps) in the GUI thread
        self._feed_monitor(request)
        if not self._resume_event.is_set():
            self.session.progress.pause()  # the clocks stand still
            self._pausedByRun.emit(True)
            self._resume_event.wait()
            self.session.progress.resume()
            self._pausedByRun.emit(False)
        return self._stop_event.is_set() or (self._watcher is not None and self._watcher.check())

    def _feed_monitor(self, request):
        """While a measurement runs the Monitor tab cannot read the instruments, so the measurement does it: at the
        end of a point, at most once per Monitor period, it hands the monitored parameters to the tab. What the point
        measured or set is taken from the cache (no extra reading); the others are read here. The refresh time is the
        Monitor period at best: it cannot be shorter than a point."""
        station = self.services.station
        now = time.monotonic()
        if not station.monitor_active or now - self._last_monitor < station.monitor_period:
            return
        monitored = station.monitored()
        if not monitored:
            return
        self._last_monitor = now
        fresh = source_chain_ids([*(p for _, p in request.measured), *self._swept])
        results = []
        for parameter in monitored:
            try:
                reading = latest_for_monitor(parameter) if id(parameter) in fresh else read_for_monitor(parameter)
            except Exception as e:  # a parameter that cannot be read must not disturb the measurement
                results.append((id(parameter), None, f"{type(e).__name__}: {e}"))
                continue
            if reading is not None:
                results.append((id(parameter), reading, ""))
        if results:
            self.monitorReadings.emit(results)

    # ================= controlling a run =================
    def toggle_pause(self):
        """Pause or resume the running measurement. A pause takes effect after the current point; asking to
        resume before that cancels it."""
        if self.state == RUNNING:
            self._resume_event.clear()
            self._set_state(PAUSING)
            self.services.status.show("Pausing after the current point...")
        elif self.state in (PAUSING, PAUSED):
            self._resume_event.set()
            self._set_state(RUNNING)

    def stop(self):
        """Stop the running measurement: dond ends cleanly after the current point (also when paused)."""
        if not self.running or self._stop_event.is_set():
            return
        self.session.stopped = True
        self._stop_event.set()
        self._resume_event.set()  # a paused run wakes up and ends
        self._set_state(STOPPING_RAMP if self._ramp_after_stop else STOPPING)
        self.services.status.show("Stopping after the current point...")

    def stop_and_ramp_to_zero(self):
        """Stop the running measurement, then bring every swept parameter to 0 at its maximum ramp rate.

        The measurement ends cleanly after the current point; the ramps start when it has ended. Each parameter
        is ramped by its own job, so parameters of different instruments ramp together while those of one
        instrument take turns (the gateway)."""
        if not self.running:
            return
        self._ramp_after_stop = True
        self.stop()
        self._set_state(STOPPING_RAMP)
        self.services.status.show("Stopping after the current point, then ramping to 0...")

    def _on_paused_by_run(self, paused):
        """The measurement thread is really waiting (or goes on again): say so."""
        if paused:
            if self.state in (RUNNING, PAUSING):
                self._set_state(PAUSED)
            self.services.status.show("Measurement paused. Press Resume to go on.")
        elif self.running and self.state not in (STOPPING, STOPPING_RAMP):
            self._set_state(RUNNING)
            self.services.status.show("Measurement resumed.", 3000)

    def _on_run_ids(self, ids):
        """The datasets about to be written: the session keeps their run ids."""
        if self.session is not None:
            self.session.run_ids.extend(ids)

    def _on_repetition(self, index, total):
        if total > 1 and self.running:
            self.services.status.show(f"Running repetition {index} of {total}...")

    # ================= the end of a run =================
    def _on_error(self, err):
        self.session.failed = True
        error = err[1]
        # QCoDeS wraps messages in tuples of (message, context...): show the message itself
        text = error.args[0] if getattr(error, "args", None) else error
        self.services.status.show(f"Experiment error: {text}", 8000)

    def _on_finished(self):
        """Runs after the measurement thread ended, however it ended: end of the sweep, Stop or an error."""
        session = self.session
        if self._watcher is not None:
            session.reason = self._watcher.reason or ""
        # ramp to 0 when "Stop and ramp to 0" was pressed, or when "Ramp to 0 when finished" is ticked and the
        # measurement ended by itself, by a breakout condition or by Stop (an error is not one of them)
        ramp, self._ramp_after_stop = self._ramp_after_stop, False
        ramp = ramp or (bool(session.request.ramp_when_finished()) and not session.failed)
        self._set_state(IDLE)
        self.runFinished.emit(session)  # the tabs unlock their inputs, the plot ends, the explorer shows the run
        if not session.failed:
            if session.reason and not session.stopped:
                self.services.status.show(f"Experiment stopped, {session.reason}", 10000)
            else:
                self.services.status.show("Experiment stopped." if session.stopped else "Experiment finished.", 3000)
        if ramp:
            self._ramp_swept_parameters_to_zero()
        elif session.failed and self.services.settings.ramp_on_error:
            self._ramp_changed_parameters_after_error()

    # ================= ramping to 0 =================
    def _ramp_swept_parameters_to_zero(self):
        """Ramp every swept parameter to 0 (the measurement has ended)."""
        started = self.services.ramp.start(self._swept, self._report_ramp)
        if started:
            self.services.status.show(f"Ramping {started} parameter(s) to 0...")

    def _ramp_changed_parameters_after_error(self):
        """A driver error ended the measurement: bring the experiment parameters the application changed to 0 (the
        others were never changed, there is nothing to undo), each at its maximum ramp rate."""
        parameters = self.services.ramp.settable_parameters(changed_only=True)
        if not parameters:
            return
        self.services.status.show(f"The measurement failed: ramping {len(parameters)} changed parameter(s) to 0...", 10000)
        self.services.ramp.start(parameters, self._report_error_ramp)

    def _report_error_ramp(self, problems):
        if problems:
            self.services.status.show("After the error, ramp to 0: " + "; ".join(problems), 20000)
        else:
            self.services.status.show("The measurement failed; the changed parameters are at 0.", 10000)

    def _report_ramp(self, problems):
        if problems:
            self.services.status.show("Ramp to 0: " + "; ".join(problems), 15000)
        else:
            self.services.status.show("Measurement stopped, swept parameters at 0.", 8000)
