"""Live plot panel of the Sweep tab: run info, plot, axis selectors and refresh controls."""
from datetime import datetime, timedelta

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget, QWidgetAction,
)

from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb

from mesoscopy.core.live_data import fetch_run_data, previous_run_ids
from mesoscopy.core.plot_math import derivative
from mesoscopy.core.plotting import MplCanvas
from mesoscopy.core.run_tags import get_run_tags, set_notes, set_tag
from mesoscopy.ui.tabs.run_notes import NotesDialog, TagPicker

MIN_REFRESH_S, MAX_REFRESH_S, DEFAULT_REFRESH_S = 1, 3600, 2
DEFAULT_PAST_CURVES, MAX_PAST_CURVES = 10, 999  # earlier curves drawn behind the current one
PAST_ALPHAS = (0.12, 0.5)  # the oldest curve is the faintest
PAST_REDRAW_MS = 250  # earlier runs arrive one by one: draw them in batches
# The earlier runs kept for the faded curves. Sized for a 16 GB Windows 11 PC, where the system, QCoDeS, the live data
# of the run and the other programs of the lab already take several GB: 256 MiB is about 1.6 % of the RAM, enough for
# ~150 runs of 100 000 points (two float64 columns each).
PAST_CACHE_MAX_BYTES = 256 * 2**20  # the default; the Settings window changes it (``set_past_cache_limit``)
LIVE_FIRST_SWEEP_MS = 300  # the first sweep of a run is redrawn at most this often as its points arrive


def format_duration(seconds):
    """Seconds -> 'H:MM:SS' ('--:--:--' if unknown)."""
    if seconds is None:
        return "--:--:--"
    return str(timedelta(seconds=int(round(seconds))))


class _FetchSignals(QObject):
    done = pyqtSignal(int, object, str)  # token, data or None, error message


class _FetchRunnable(QRunnable):
    """Reads the run from the database outside the GUI thread."""

    def __init__(self, token, db_file, run_id):
        super().__init__()
        self.token, self.db_file, self.run_id = token, db_file, run_id
        self.signals = _FetchSignals()

    def run(self):
        try:
            data = fetch_run_data(self.db_file, self.run_id)
            self.signals.done.emit(self.token, data, "")
        except Exception as e:
            self.signals.done.emit(self.token, None, f"{type(e).__name__}: {e}")


class _PastSignals(QObject):
    ids = pyqtSignal(int, object)            # token, ids of the earlier runs (oldest first)
    run = pyqtSignal(int, str, int, object)  # token, database, run id, data (None when it cannot be read)


class _PastRunnable(QRunnable):
    """Reads the earlier runs of the experiment, newest first, one by one (the ones already known are skipped)."""

    def __init__(self, token, db_file, run_id, count, known):
        super().__init__()
        self.token, self.db_file, self.run_id, self.count, self.known = token, db_file, run_id, count, known
        self.cancelled = False
        self.signals = _PastSignals()

    def run(self):
        try:
            ids = previous_run_ids(self.db_file, self.run_id, self.count)
        except Exception:
            ids = []
        self.signals.ids.emit(self.token, ids)
        for run_id in reversed(ids):
            if self.cancelled:
                return
            if (self.db_file, run_id) in self.known:
                continue
            try:
                data = fetch_run_data(self.db_file, run_id, curves_only=True)
            except Exception:
                data = None
            self.signals.run.emit(self.token, self.db_file, run_id, data)


class LivePlotPanel(QWidget):
    """Plot of the current run that follows the acquisition.

    Above the plot: run number, measurement name, elapsed and remaining time.
    Below: x and y axis selectors (any swept or measured parameter) with multiplication factors,
    and a Refresh button, an automatic refresh option and its period in seconds.
    """

    valuePicked = pyqtSignal(float, str)  # x (in the units of the parameter: the factor is taken out) and the x axis name
    rangePicked = pyqtSignal(float, float, str)  # start and stop of a drag, likewise, and the x axis name
    runAnnotated = pyqtSignal(str, int, str, str)  # database, run id, "tag" or "notes", the value written
    limitRequested = pyqtSignal(str, str, float)  # x axis name, "max" or "min", the value: set that safe limit of the parameter

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pick_label = None   # the Start or Stop field a click fills in (set by the Measurement tab), or None
        self._curve = None        # (x, y) of the newest curve as drawn, for the extrema of the right-click menu
        self._markers = None      # (x axis name, [(label, value)]): the Start and Stop of the armed axis, drawn as lines
        self._cursor_x = None     # x under the mouse pointer (as drawn), None when it is off the axes
        self.limit_provider = None  # f(x axis name) -> (parameter name, minimum, maximum) when its safe limits can be set
        self._token = 0
        self._db_file = None
        self._run_id = None
        self._measurement_name = ""
        self._progress = None
        self._running = False
        self._data = None
        self._fetching = False
        self._refresh_again = False
        self._live_runs = {}      # run id -> LiveRun: the data of the runs in progress, pushed by QCoDeS
        self._live_version = None  # what was last drawn from a LiveRun
        self._drawn_key = None     # what the plot shows: nothing is redrawn while it would look the same
        self._stale = False        # data came while the panel was hidden
        self._factors = [1.0, 1.0]
        self._past_ids = []      # the earlier runs of the experiment, oldest first
        self._past_cache_limit = PAST_CACHE_MAX_BYTES
        self._past_cache = {}    # (database, run id) -> data of an earlier run, None if it cannot be drawn
        self._past_key = None    # what the earlier runs were asked for: (token, number)
        self._past_job = None
        self._dataset_names = []  # the datasets of the run in progress (several only with advanced settings)
        self._dataset_ids = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # --- above the plot: run info ---
        self.run_label = QLabel("No run yet")
        font = self.run_label.font()
        font.setBold(True)
        self.run_label.setFont(font)
        self.run_label.setWordWrap(True)
        layout.addWidget(self.run_label)
        # several datasets (the advanced settings): which one the plot follows; hidden for a single dataset
        self.dataset_row = QWidget()
        dataset_layout = QHBoxLayout(self.dataset_row)
        dataset_layout.setContentsMargins(0, 0, 0, 0)
        dataset_layout.addWidget(QLabel("Dataset:"))
        self.dataset_combo = QComboBox()
        self.dataset_combo.currentIndexChanged.connect(self._dataset_chosen)
        dataset_layout.addWidget(self.dataset_combo, 1)
        self.dataset_row.setVisible(False)
        layout.addWidget(self.dataset_row)
        times = QHBoxLayout()
        self.elapsed_field = self._read_only_field()
        self.remaining_field = self._read_only_field()
        times.addWidget(QLabel("Elapsed time:"))
        times.addWidget(self.elapsed_field)
        times.addWidget(QLabel("Remaining time:"))
        times.addWidget(self.remaining_field)
        times.addStretch()
        layout.addLayout(times)

        # --- the plot ---
        self.canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.canvas.setMinimumWidth(300)
        layout.addWidget(self.canvas, 1)
        self.cursor_label = QLabel("")  # x and y under the mouse cursor, in the units of the axes
        self.cursor_label.setMinimumHeight(self.cursor_label.fontMetrics().height() + 2)
        self.cursor_label.setToolTip("Position of the mouse cursor over the plot (x and y as drawn, with the factors applied)")
        self.canvas.cursorMoved.connect(self._show_cursor)
        self.canvas.cursorLeft.connect(lambda: self.cursor_label.setText(""))
        layout.addWidget(self.cursor_label)
        self.pick_label = QLabel("")  # which field a click on the plot fills in
        self.pick_label.setStyleSheet("color: #1565c0;")
        self.pick_label.setVisible(False)
        layout.addWidget(self.pick_label)
        self.canvas.clicked.connect(self._on_canvas_clicked)
        self.canvas.dragged.connect(self._on_canvas_dragged)
        self.canvas.cursorMoved.connect(lambda x, _y: setattr(self, "_cursor_x", x))
        self.canvas.cursorLeft.connect(lambda: setattr(self, "_cursor_x", None))
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self._show_plot_menu)

        # --- below the plot: axes ---
        self.x_combo, self.x_factor = QComboBox(), QLineEdit("1")
        self.y_combo, self.y_factor = QComboBox(), QLineEdit("1")
        for index, (name, combo, factor) in enumerate(
            (("X axis:", self.x_combo, self.x_factor), ("Y axis:", self.y_combo, self.y_factor))
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            row.addWidget(combo, 1)
            row.addWidget(QLabel("×"))
            factor.setMaximumWidth(80)
            factor.setToolTip("Multiplication factor applied to the live plot (e.g. 1e3, 0.001)")
            row.addWidget(factor)
            if name == "Y axis:":  # right after the gain of the y axis
                self.derivative_button = QPushButton("\u2202y/\u2202x")
                self.derivative_button.setCheckable(True)
                self.derivative_button.setToolTip(
                    "Show the derivative of the y axis with respect to the x axis (as drawn, factors included), for "
                    "every curve. Where x does not change between two points there is a gap.")
                self.derivative_button.toggled.connect(self._redraw)
                row.addWidget(self.derivative_button)
            layout.addLayout(row)
            combo.currentIndexChanged.connect(self._redraw)
            factor.textChanged.connect(lambda _text, i=index: self._on_factor_changed(i))

        # --- below the plot: refresh ---
        refresh_row = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        self.auto_checkbox = QCheckBox("Refresh automatically")
        self.auto_checkbox.setChecked(True)
        self.auto_checkbox.toggled.connect(self._update_auto_timer)
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(MIN_REFRESH_S, MAX_REFRESH_S)
        self.refresh_spin.setValue(DEFAULT_REFRESH_S)
        self.refresh_spin.setSuffix(" s")
        self.refresh_spin.setToolTip("Refresh period in seconds (1 to 3600)")
        self.refresh_spin.valueChanged.connect(self._update_auto_timer)
        refresh_row.addWidget(self.refresh_button)
        refresh_row.addWidget(self.auto_checkbox)
        refresh_row.addWidget(QLabel("every"))
        refresh_row.addWidget(self.refresh_spin)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)
        past_row = QHBoxLayout()
        self.past_spin = QSpinBox()
        self.past_spin.setRange(0, MAX_PAST_CURVES)
        self.past_spin.setValue(DEFAULT_PAST_CURVES)
        self.past_spin.setToolTip(
            "Earlier curves drawn faded behind the current one (0: only the current curve).\n"
            "Multi-dimensional runs and runs of traces with a sweep: the previous sweeps of the run.\n"
            "One-dimensional runs and single traces: the previous runs of the same experiment."
        )
        self.past_spin.valueChanged.connect(self._on_past_changed)
        self.past_label = QLabel("")
        self.past_label.setStyleSheet("color: gray; font-size: 0.9em;")
        past_row.addWidget(QLabel("Past curves:"))
        past_row.addWidget(self.past_spin)
        past_row.addWidget(self.past_label, 1)
        layout.addLayout(past_row)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-size: 0.9em;")
        layout.addWidget(self.status_label)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._clock_running = False  # the clocks follow the shared 1 Hz tick (``tick``), see services/ticker.py
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._live_redraw = QTimer(self)  # while the first sweep of a run comes in, show it as it grows
        self._live_redraw.setSingleShot(True)
        self._live_redraw.timeout.connect(self.refresh)
        self._past_pool = QThreadPool(self)  # earlier runs are read on their own: they never delay the current run
        self._past_pool.setMaxThreadCount(1)
        self._past_redraw = QTimer(self)
        self._past_redraw.setSingleShot(True)
        self._past_redraw.timeout.connect(self._redraw)

    @staticmethod
    def _read_only_field():
        field = QLineEdit("--:--:--")
        field.setReadOnly(True)
        field.setMaximumWidth(90)
        return field

    # ----- run lifecycle -----
    def begin_run(self, db_file, measurement_name, progress, dataset_names=()):
        """Start following a new run; clears the previous plot."""
        self._token += 1
        self._db_file = db_file
        self._run_id = None
        self._measurement_name = measurement_name
        self._progress = progress
        self._running = True
        self._data = None
        self._refresh_again = False
        self._live_runs, self._live_version, self._drawn_key, self._stale = {}, None, None, False
        self._past_ids, self._past_key = [], None
        self.past_label.setText("")
        self._dataset_names, self._dataset_ids = list(dataset_names), []
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        self.dataset_combo.addItems(self._dataset_names)
        self.dataset_combo.blockSignals(False)
        self.dataset_row.setVisible(len(self._dataset_names) > 1)
        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_combo.clear()
        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)
        self.canvas.axes.cla()
        self.canvas.draw_idle()
        self.run_label.setText(f"Run: starting – {measurement_name}")
        self.status_label.setText("Waiting for the first points...")
        self._tick()
        self._clock_running = True
        self._update_auto_timer()
        token = self._token
        QTimer.singleShot(1000, lambda: self.refresh() if token == self._token else None)

    def set_run_id(self, run_id):
        """The run id the measurement will get (known as soon as the worker has opened the database). With several
        datasets ``set_run_ids`` follows and picks the chosen one."""
        if len(self._dataset_names) <= 1:
            self._run_id = run_id

    def set_run_ids(self, run_ids):
        """The ids of the datasets about to be written (one per dataset): follow the one chosen in the selector."""
        if list(run_ids) != self._dataset_ids:
            self._release_previous_run(set(run_ids))
        self._dataset_ids = list(run_ids)
        if len(self._dataset_names) > 1 and len(self._dataset_ids) == len(self._dataset_names):
            self._run_id = self._dataset_ids[max(self.dataset_combo.currentIndex(), 0)]

    def _dataset_chosen(self, index):
        """The user picks another dataset of the measurement: show it."""
        if 0 <= index < len(self._dataset_ids):
            self._run_id = self._dataset_ids[index]
            self._token += 1  # an answer for the previous dataset is dropped
            self._data = None
            self._live_version, self._drawn_key = None, None
            self._past_key = None
            for combo in (self.x_combo, self.y_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.blockSignals(False)
            self.canvas.axes.cla()
            self.canvas.draw_idle()
            self.refresh()

    def end_run(self):
        """The measurement is over (finished or failed): freeze the clocks and do a last refresh."""
        self._running = False
        if self._progress is not None:
            self._progress.finish()
        self._clock_running = False
        self._refresh_timer.stop()
        self._live_redraw.stop()
        self._tick()
        self.refresh(force=True)

    def shutdown(self):
        """Stop timers and wait for a running database read (used when the window closes)."""
        self._token += 1
        self._clock_running = False
        self._refresh_timer.stop()
        self._live_redraw.stop()
        if self._past_job is not None:
            self._past_job.cancelled = True
        self._pool.waitForDone(3000)
        self._past_pool.waitForDone(3000)

    # ----- clocks -----
    def tick(self):
        """The shared 1 Hz tick: move the clocks while a run is in progress."""
        if self._clock_running:
            self._tick()

    def _tick(self):
        if self._progress is None:
            return
        self.elapsed_field.setText(format_duration(self._progress.elapsed()))
        self.remaining_field.setText(format_duration(self._progress.remaining()))

    def _update_auto_timer(self):
        """(Re)start or stop the automatic refresh according to the checkbox, period and run state."""
        if self._running and self.auto_checkbox.isChecked():
            self._refresh_timer.start(self.refresh_spin.value() * 1000)
        else:
            self._refresh_timer.stop()

    # ----- reading the data -----
    def showEvent(self, event):
        super().showEvent(event)
        self._tick()  # the clocks did not move while the panel was hidden
        if self._stale:  # nothing was drawn while the tab was hidden
            self._stale = False
            self.refresh(force=True)

    def _release_previous_run(self, keep):
        """A new run starts: let go of the data of the previous one (live buffers, drawn data, plot)."""
        self._live_runs = {run_id: live for run_id, live in self._live_runs.items() if run_id in keep}
        self._data, self._live_version, self._drawn_key = None, None, None
        self._redraw()

    def add_live_run(self, live):
        """A dataset of the measurement is being written: its data is pushed here, so it is not read back."""
        self._live_runs[live.run_id] = live
        self.refresh()

    def live_data_changed(self):
        """Rows arrived. While the first sweep of the run is still coming in, draw it as it grows, so that a leakage
        or a wrong range shows at once; afterwards the refresh period decides (a map is only redrawn if there is
        something new)."""
        if not (self._running and self.auto_checkbox.isChecked()) or self._live_redraw.isActive():
            return
        first = self._data is None or self._data["n_points"] <= (self._progress.inner_points if self._progress else 0)
        if first:
            self._live_redraw.start(LIVE_FIRST_SWEEP_MS)

    def refresh(self, force=False):
        """Show the data of the run: from QCoDeS' live feed when there is one, else read from the database (in a
        background thread). Nothing is drawn again if nothing changed since the last time (unless ``force``)."""
        if self._db_file is None or self._run_id is None:
            return
        if not self.isVisible():  # hidden tab (or minimised window): draw when it is shown again
            self._stale = True
            return
        live = self._live_runs.get(self._run_id)
        if live is not None and live.ready:
            if force or (id(live), live.version) != self._live_version:
                self._live_version = (id(live), live.version)
                data = live.snapshot()
                if data is None:
                    self.status_label.setText("Waiting for the first points...")
                else:
                    self._show_data(data)
            return
        if self._fetching:
            self._refresh_again = True  # do it again once the current read is done
            return
        self._fetching = True
        runnable = _FetchRunnable(self._token, self._db_file, self._run_id)
        runnable.signals.done.connect(self._on_fetched)
        self._pool.start(runnable)

    def _show_data(self, data):
        self._data = data
        self.run_label.setText(f"Run {data['run_id']} – {self._measurement_name}")
        self._update_axis_choices(data)
        self._request_past(data)
        self._redraw()
        self.status_label.setText(f"Last refresh {datetime.now():%H:%M:%S} – {data['n_points']} points")

    def _on_fetched(self, token, data, error):
        self._fetching = False
        if token == self._token:  # ignore the answer for a previous run
            if error:
                self.status_label.setText(f"Refresh failed: {error}")
            elif data is None:
                self.status_label.setText("Waiting for the run to appear in the database...")
            else:
                self._show_data(data)
        if self._refresh_again:
            self._refresh_again = False
            self.refresh()

    # ----- axes -----
    @staticmethod
    def _choice_text(data, name):
        unit = data["units"].get(name)
        return f"{name} ({unit})" if unit else name

    def _update_axis_choices(self, data):
        """List every plottable parameter in both selectors; keep the user's choice when possible."""
        names = data["setpoints"] + data["dependents"]
        if [self.x_combo.itemData(i) for i in range(self.x_combo.count())] == names:
            return
        previous = (self.x_combo.currentData(), self.y_combo.currentData())
        defaults = (
            self._progress.x_default if self._progress and self._progress.x_default in names
            else (data["setpoints"] or names)[0],
            (data["dependents"] or names)[0],
        )
        if data.get("trace_values"):  # a trace is shown against its own axis
            defaults = ((data["trace_axes"] or [defaults[0]])[0], data["trace_values"][0])
        for combo, wanted, default in zip((self.x_combo, self.y_combo), previous, defaults):
            combo.blockSignals(True)
            combo.clear()
            for name in names:
                combo.addItem(self._choice_text(data, name), name)
            combo.setCurrentIndex(combo.findData(wanted if wanted in names else default))
            combo.blockSignals(False)

    def _on_factor_changed(self, index):
        edit = (self.x_factor, self.y_factor)[index]
        try:
            value = float(edit.text())
            if not np.isfinite(value):
                raise ValueError
        except ValueError:
            edit.setStyleSheet("background-color: #f4a6a6;")  # invalid: keep the last valid factor
            return
        edit.setStyleSheet("")
        self._factors[index] = value
        self._redraw()

    # ----- drawing -----
    def _redraw(self, *_):
        """Draw the plot, unless it would look as it does: same data, axes, factors, derivative and earlier curves."""
        data = self._data
        xname, yname = self.x_combo.currentData(), self.y_combo.currentData()
        if not self.isVisible():
            self._drawn_key, self._stale = None, True
            return
        slope, past = self.derivative_button.isChecked(), self.past_spin.value()
        have = sum((self._db_file, r) in self._past_cache for r in self._past_ids)
        key = ("empty",) if data is None else (
            data["run_id"], data["n_points"], data["completed"], xname, yname, tuple(self._factors), slope, past, have,
            repr(self._markers))
        if key == self._drawn_key:
            return
        self._drawn_key = key
        ax = self.canvas.axes
        ax.cla()
        self._curve = None
        if data is None or xname not in data["arrays"] or yname not in data["arrays"]:
            self.canvas.draw_idle()
            return
        fx, fy = self._factors
        x_all, y_all = data["arrays"][xname], data["arrays"][yname]
        n = min(len(x_all), len(y_all))
        traces = data.get("trace_length") and (xname in data["trace_axes"] + data["trace_values"]
                                               or yname in data["trace_axes"] + data["trace_values"])
        start = 0
        if not data.get("single_curve", True):
            # a map: only the sweeps that are drawn (the newest and the faded ones behind it) are worked on, not the grid
            inner = self._row_length(data["trace_length"] if traces else None)
            if inner and inner > 1 and n > inner:
                start = max((-(-n // inner) - (self.past_spin.value() + 1)) * inner, 0)
        x, y = np.real(x_all[start:n]) * fx, y_all[start:n] * fy
        complex_y = np.iscomplexobj(y)
        parts = [("Re", y.real), ("Im", y.imag)] if complex_y else [("", y)]  # drawn in C0, C1
        if n and np.isfinite(x).any() and np.isfinite(y).any():
            if data.get("single_curve", True):  # one curve: the earlier ones are the earlier runs
                earlier = self._past_curves(xname, yname, fx, fy)
                for k, (suffix, values) in enumerate(parts):
                    segments = [np.column_stack([px, derivative(px, py.real if not k else py.imag) if slope
                                                 else (py.real if not k else py.imag)])
                                for px, py in earlier]
                    self._draw_faded(ax, segments, f"C{k}")
                    shown = derivative(x, values) if slope else values
                    if k == 0:
                        self._curve = (x, values)  # not differentiated: the menu offers both
                    ax.plot(*self._joined(x, shown), '.-', ms=4, color=f"C{k}", label=suffix)
            else:  # the sweeps of the run: the earlier ones faded, the newest one on top
                past = self.past_spin.value()
                for k, (suffix, values) in enumerate(parts):
                    xs, ys = self._split_into_sweeps(x, values, data["trace_length"] if traces else None)
                    plain = ys[-1]  # (``x`` starts at a sweep boundary: the rows are the same as for the whole grid)
                    if slope:  # each sweep (row) has its own derivative
                        ys = np.array([derivative(row_x, row_y) for row_x, row_y in zip(xs, ys)])
                    xs, ys = xs[-(past + 1):], ys[-(past + 1):]
                    if len(xs) > 1:
                        self._draw_faded(ax, list(np.stack([xs[:-1], ys[:-1]], axis=-1)), f"C{k}")
                    if k == 0:
                        self._curve = (xs[-1], plain)
                    ax.plot(*self._joined(xs[-1], ys[-1]), '.-', ms=4, color=f"C{k}", label=suffix)
        x_label, y_label = self._axis_label(data["labels"][xname], fx), self._axis_label(data["labels"][yname], fy)
        ax.set_xlabel(x_label)
        ax.set_ylabel(f"\u2202({y_label}) / \u2202({x_label})" if slope else y_label)
        self._draw_markers(ax, xname, fx)
        if complex_y:
            ax.legend(loc="best")
        self.canvas.draw_idle()

    # ----- picking values from the plot (run-to-run feedback) -----
    def set_markers(self, xname, marks):
        """Draw vertical lines at the Start and Stop of the axis being filled in: ``marks`` = [(label, value)] in the units
        of the parameter ``xname`` (they only show when that is the x axis of the plot). None: no lines."""
        markers = (xname, list(marks)) if xname and marks else None
        if repr(markers) != repr(self._markers):
            self._markers = markers
            self._redraw()

    def _draw_markers(self, ax, xname, factor):
        if self._markers is None or self._markers[0] != xname:
            return
        for (label, value), colour in zip(self._markers[1], ("C1", "C2")):  # orange, green: told apart by the label too
            ax.axvline(value * factor, color=colour, linestyle="-", linewidth=1.2)
            ax.annotate(label, (value * factor, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -3),
                        textcoords="offset points", va="top", fontsize=8, color=colour)

    def _on_canvas_dragged(self, x0, x1):
        if self._pick_label:
            self.rangePicked.emit(self._x_to_value(x0), self._x_to_value(x1), self.x_combo.currentData() or "")

    def set_pick_target(self, label):
        """The Measurement tab says which Start or Stop field a click on the plot fills in (None: none)."""
        self._pick_label = label
        self.pick_label.setText(f"Click on the plot, or right-click for the maximum or minimum, to fill in: {label}"
                                if label else "")
        self.pick_label.setVisible(bool(label))

    def _x_to_value(self, x):
        """A position on the x axis as the parameter's value (the factor of the axis is taken out)."""
        return x / self._factors[0]

    def _on_canvas_clicked(self, x, _y):
        if self._pick_label:
            self.valuePicked.emit(self._x_to_value(x), self.x_combo.currentData() or "")

    def _show_plot_menu(self, position):
        """Right click: the x of the maximum or of the minimum of what is drawn, to fill in the armed field."""
        menu = QMenu(self.canvas)
        curve = self._curve
        finite = None
        if curve is not None:
            x, y = np.asarray(curve[0], float), np.asarray(curve[1], float)
            good = np.isfinite(x) & np.isfinite(y)
            finite = (x[good], y[good]) if good.any() else None
        name = self.y_combo.currentData() or "y"
        if finite is None:
            menu.addAction("Nothing is drawn yet").setEnabled(False)
        elif not self._pick_label:
            menu.addAction("Click in a Start or Stop field first").setEnabled(False)
        if finite is not None:
            slope = derivative(finite[0], finite[1])  # d(y)/d(x) of the curve as drawn (factors included)
            ok = np.isfinite(slope)
            for words, values, xs in ((f"of {name}", finite[1], finite[0]),
                                      ("of \u2202y/\u2202x", slope[ok], finite[0][ok])):
                if not len(values):
                    continue
                for kind, pick in (("maximum", np.argmax), ("minimum", np.argmin)):
                    at = float(xs[int(pick(values))])
                    action = menu.addAction(f"Use x at the {kind} {words}: {at:.6g}")
                    action.setEnabled(bool(self._pick_label))
                    action.triggered.connect(lambda _c=False, a=at: self.valuePicked.emit(
                        self._x_to_value(a), self.x_combo.currentData() or ""))
        limits = self.limit_provider(self.x_combo.currentData() or "") if self.limit_provider else None
        if limits is not None and self._cursor_x is not None:
            menu.addSeparator()
            value = self._x_to_value(self._cursor_x)
            pname, low, high = limits
            for which, word, now in (("max", "maximum", high), ("min", "minimum", low)):
                action = menu.addAction(f"Set {pname} safe {word} to {value:.6g}" + (f" (now {now:g})" if now is not None else ""))
                action.triggered.connect(lambda _c=False, w=which, v=value: self.limitRequested.emit(
                    self.x_combo.currentData() or "", w, v))
        self._add_run_annotation_items(menu)
        menu.exec(self.canvas.mapToGlobal(position))

    # ----- the tag and the notes of the run shown (the same as in the Data tab's experiment explorer) -----
    def _add_run_annotation_items(self, menu):
        """Once the run has ended: the tag (coloured dots) and the notes of the run shown, to read or change."""
        if self._running or not self._db_file or self._run_id is None or self._data is None:
            return
        try:
            tag, notes = get_run_tags(self._db_file, self._run_id)
        except Exception:
            return  # the run is not readable (yet): nothing to annotate
        run_id = self._run_id
        menu.addSeparator()
        picker = TagPicker(tag)
        picker.tagChosen.connect(lambda chosen, t=tag: (menu.close(), self._write_tag(run_id, "" if chosen == t else chosen)))
        action = QWidgetAction(menu)
        action.setDefaultWidget(picker)
        menu.addAction(action)
        menu.tag_picker = picker
        menu.addAction("Edit notes..." if notes else "Add notes...").triggered.connect(
            lambda _c=False: self._edit_notes(run_id, notes))
        delete = menu.addAction("Delete note")
        delete.setEnabled(bool(notes))
        delete.triggered.connect(lambda _c=False: self._write_notes(run_id, ""))

    def _write_tag(self, run_id, tag):
        if self._write(set_tag, run_id, tag, "tag"):
            self._announce(run_id, "tag", tag)
            self.status_label.setText(f"Run {run_id}: " + (f"tag {tag}." if tag else "tag removed."))

    def _edit_notes(self, run_id, notes):
        dialog = NotesDialog(self.window(), f"Notes of run {run_id}", notes)
        if dialog.exec() and dialog.notes() != notes:
            self._write_notes(run_id, dialog.notes())

    def _write_notes(self, run_id, notes):
        if self._write(set_notes, run_id, notes, "notes"):
            self._announce(run_id, "notes", notes)
            self.status_label.setText(f"Run {run_id}: " + ("notes saved." if notes else "note deleted."))

    def _announce(self, run_id, field, value):
        """Tell the Data tab, which lists this run, that its tag or notes changed."""
        captured = (self._data or {}).get("run_id", run_id)  # the number the explorer shows
        self.runAnnotated.emit(self._db_file, int(captured), field, value)

    def _write(self, writer, run_id, value, what):
        try:
            writer(self._db_file, run_id, value)
        except Exception as e:  # e.g. the database is locked by a measurement writing at that very moment
            QMessageBox.warning(self.window(), "Run metadata", f"Could not write the {what}: {type(e).__name__}: {e}")
            return False
        return True

    @staticmethod
    def _joined(x, y):
        """The points of the current curve without the ones that are missing (NaN), so that the line joins each point to
        the next one that was measured instead of breaking at every gap."""
        good = np.isfinite(x) & np.isfinite(y)
        return (x, y) if good.all() else (x[good], y[good])

    def _show_cursor(self, x, y):
        """x and y of the cursor, named as the axes are."""
        names = []
        for combo in (self.x_combo, self.y_combo):
            names.append(combo.currentData() or "")
        self.cursor_label.setText(f"x = {x:.6g}     y = {y:.6g}")
        self.cursor_label.setToolTip(f"x: {names[0]}\ny: {names[1]}")

    @staticmethod
    def _axis_label(label, factor):
        return label if factor == 1 else f"{label} × {factor:g}"

    def _row_length(self, row_length=None):
        """Points of one row of a map: a trace, or the inner (fastest) sweep; None when it is not known."""
        return row_length or (self._progress.inner_points if self._progress else None)

    def _split_into_sweeps(self, x, y, row_length=None):
        """Rows = one inner (fastest) sweep each, or one trace each (``row_length`` points); a single row for
        one-dimensional runs."""
        inner = self._row_length(row_length)
        if inner and inner > 1 and len(x) > inner:
            rows = -(-len(x) // inner)
            pad = rows * inner - len(x)
            if pad:  # the sweep in progress is incomplete
                x = np.concatenate([x, np.full(pad, np.nan)])
                y = np.concatenate([y, np.full(pad, np.nan)])
            return x.reshape(rows, inner), y.reshape(rows, inner)
        return x[None, :], y[None, :]

    # ----- earlier curves -----
    @staticmethod
    def _draw_faded(ax, segments, colour="C0"):
        """Draw curves ([(n, 2) arrays], oldest first) as one faded collection: cheap, even for hundreds of them."""
        if not len(segments):
            return
        base = to_rgb(colour)
        alphas = np.linspace(*PAST_ALPHAS, len(segments))
        ax.add_collection(LineCollection(segments, colors=[(*base, a) for a in alphas], linewidths=1))
        ax.autoscale_view()

    def _past_curves(self, xname, yname, fx, fy):
        """The earlier runs that can be drawn against the same axes: [(x, y)] (y complex for a complex parameter),
        oldest first. Runs that were made of other parameters, or of several sweeps, are left out (the label says
        how many)."""
        curves, missing, skipped = [], 0, 0
        for run_id in self._past_ids[-self.past_spin.value():] if self.past_spin.value() else []:
            data = self._past_cache.get((self._db_file, run_id), False)
            if data is False:
                missing += 1
            elif data is None or not data["single_curve"] or xname not in data["arrays"] or yname not in data["arrays"]:
                skipped += 1
            else:
                x, y = np.real(data["arrays"][xname]) * fx, data["arrays"][yname] * fy
                n = min(len(x), len(y))
                if n:
                    curves.append((x[:n], y[:n]))
        text = f"{len(curves)} earlier run{'' if len(curves) == 1 else 's'} of this experiment"
        if skipped:
            text += f", {skipped} left out (other parameters or sweeps)"
        if missing:
            text += f", reading {missing} more..."
        self.past_label.setText(text if self._past_ids and self.past_spin.value() else "")
        return curves

    def set_past_cache_limit(self, nbytes):
        """Memory the earlier runs may use (from the Settings window); what is over it is dropped at once."""
        self._past_cache_limit = int(nbytes)
        self._trim_past_cache()

    def _trim_past_cache(self):
        """Keep the earlier runs within the memory limit. The runs that are not drawn any more go first, then the
        oldest ones (they are read newest first, so the order of reading says nothing about which are needed)."""
        size = lambda d: sum(a.nbytes for a in d["arrays"].values()) if d else 0
        total = sum(size(d) for d in self._past_cache.values())
        wanted = {(self._db_file, r) for r in self._past_ids[-self.past_spin.value():]}
        for key in sorted(self._past_cache, key=lambda k: (k in wanted, k[0] != self._db_file, k[1])):
            if total <= self._past_cache_limit and len(self._past_cache) <= 2 * MAX_PAST_CURVES:
                break
            if len(self._past_cache) <= 1:
                break
            total -= size(self._past_cache.pop(key))

    def _on_past_changed(self):
        self._request_past(self._data)
        self._redraw()

    def _request_past(self, data):
        """Read the earlier runs of the experiment (in the background) when the current run is a single curve."""
        count = self.past_spin.value()
        if data is None or self._run_id is None:
            return
        if not count or not data.get("single_curve", True):  # nothing asked, or the sweeps of this run are the curves
            self.past_label.setText("")
            return
        key = (self._token, count)
        if key == self._past_key:
            return
        self._past_key = key
        if self._past_job is not None:
            self._past_job.cancelled = True  # the new request includes what it still had to read
        job = self._past_job = _PastRunnable(self._token, self._db_file, self._run_id, count, self._past_cache)
        job.signals.ids.connect(self._on_past_ids)
        job.signals.run.connect(self._on_past_run)
        self._past_pool.start(job)

    def _on_past_ids(self, token, ids):
        if token == self._token:
            self._past_ids = ids
            self._past_redraw.start(PAST_REDRAW_MS)

    def _on_past_run(self, token, db_file, run_id, data):
        self._past_cache[(db_file, run_id)] = data
        self._trim_past_cache()
        if token == self._token and not self._past_redraw.isActive():
            self._past_redraw.start(PAST_REDRAW_MS)
