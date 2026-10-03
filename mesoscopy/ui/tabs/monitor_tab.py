"""Monitor tab: live values of chosen parameters (refreshed every N seconds) and their time traces."""
from collections import deque
from datetime import datetime
import math
import time

from PyQt6.QtCore import QObject, QPointF, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from mesoscopy.core.gateway import BACKGROUND, USER, parameter_instruments
from mesoscopy.services.alarms import ACTION_TEXT
from mesoscopy.core.parameter_io import parameter_label, read_for_monitor
from mesoscopy.core.plot_math import decimate, nice_step

MIN_PERIOD_S, MAX_PERIOD_S, DEFAULT_PERIOD_S = 1, 3600, 5
MIN_WINDOW_MIN, MAX_WINDOW_MIN, DEFAULT_WINDOW_MIN = 1, 1440, 10  # duration shown by the time traces
MAX_WINDOW_S = MAX_WINDOW_MIN * 60  # history is kept for the longest duration, so the scale can be widened later
HIDDEN_REDRAW_S = 5  # seconds between two redraws of the traces while the Monitor tab is hidden
MAX_POINTS = 100_000  # safety bound on the points kept per parameter
TRACES_PER_ROW = 2
COLUMNS = ("Parameter", "Value", "Updated", "Show time trace", "")
COL_NAME, COL_VALUE, COL_TIME, COL_TRACE, COL_REMOVE = range(5)


class TimeTrace(QWidget):
    """Trace of one parameter over a selectable duration (1 minute to 24 hours).

    The x axis runs from minus the duration to 0 (0 = now), in minutes, or in hours when the duration
    is above 60 minutes, with the unit written next to the axis. The y axis shows only its minimum
    and maximum, in the parameter's unit.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []  # (epoch seconds, value)
        self._name = ""
        self._unit = ""
        self._window_s = DEFAULT_WINDOW_MIN * 60
        self.setMinimumSize(250, 140)

    def set_series(self, name, unit, points, window_s=None):
        self._name, self._unit, self._points = name, unit, list(points)
        if window_s is not None:
            self._window_s = window_s
        self.update()

    def x_unit(self):
        """'min', or 'h' when the duration is above 60 minutes."""
        return "h" if self._window_s > 3600 else "min"

    def _unit_seconds(self):
        return 3600 if self._window_s > 3600 else 60

    def x_ticks(self):
        """[(position 0..1 along the axis, label)] from minus the duration to 0, in the axis unit."""
        span = self._window_s / self._unit_seconds()
        step = nice_step(span)
        ticks = []
        for k in range(int(span / step + 1e-9) + 1):
            value = -k * step
            label = "0" if abs(value) < 1e-9 else f"{value:.6g}"
            ticks.append((1 + value / span, label))
        return ticks[::-1]

    def visible_points(self, now=None):
        """Points inside the window as (x fraction 0..1 with 1 = now, value)."""
        now = time.time() if now is None else now
        return [(1 - (now - ts) / self._window_s, value) for ts, value in self._points
                if now - ts <= self._window_s]

    def y_range(self, now=None):
        values = [v for _, v in self.visible_points(now)]
        return (min(values), max(values)) if values else None

    def y_labels(self, now=None):
        """(max text, min text) written on the y axis, or None without data."""
        limits = self.y_range(now)
        if limits is None:
            return None
        unit = f" {self._unit}" if self._unit else ""
        return f"{limits[1]:.4g}{unit}", f"{limits[0]:.4g}{unit}"

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text_color, axis_color = palette.text().color(), palette.mid().color()
        metrics = painter.fontMetrics()
        now = time.time()
        labels = self.y_labels(now)
        left = (max(metrics.horizontalAdvance(t) for t in labels) if labels else 30) + 8
        top, bottom, right = 28, 24, 36  # room for the title row, the tick labels and the unit
        plot = QRect(left, top, self.width() - left - right, self.height() - top - bottom)

        painter.setPen(text_color)
        painter.drawText(QRect(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(self._name, Qt.TextElideMode.ElideRight, self.width()))
        painter.setPen(QPen(axis_color, 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        painter.drawLine(plot.topLeft(), plot.bottomLeft())
        # x axis: minus the duration ... 0, with the unit next to the axis
        for fraction, label in self.x_ticks():
            x = plot.left() + plot.width() * fraction
            painter.setPen(QPen(axis_color, 1))
            painter.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 3))
            painter.setPen(text_color)
            painter.drawText(QRect(int(x) - 18, plot.bottom() + 4, 36, 14), Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(text_color)
        painter.drawText(QRect(plot.right() + 20, plot.bottom() + 4, right - 20, 14),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.x_unit())
        if labels is None:
            return
        # y axis: only the minimum and the maximum
        painter.drawText(QRect(0, plot.top() - 6, left - 4, 12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, labels[0])
        painter.drawText(QRect(0, plot.bottom() - 6, left - 4, 12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, labels[1])
        low, high = self.y_range(now)
        span = (high - low) or 1.0  # a flat series is drawn in the middle
        points = [
            QPointF(plot.left() + plot.width() * fraction,
                    plot.top() + plot.height() * (0.5 if high == low else 1 - (value - low) / span))
            for fraction, value in decimate(self.visible_points(now), max(plot.width(), 1))
        ]
        painter.setPen(QPen(palette.highlight().color(), 1.5))
        if len(points) > 1:
            painter.drawPolyline(QPolygonF(points))
        painter.setBrush(palette.highlight().color())
        painter.drawEllipse(points[-1], 2.5, 2.5)  # latest value


def instrument_groups(parameters):
    """[(set of instrument names, [parameters])]: the parameters split into groups that share no instrument, so that the
    groups can be read at the same time. A parameter that depends on several instruments (a delegate, a derived one) joins
    their groups into one. The parameters that touch no instrument form a group of their own."""
    groups = []  # [names, parameters]
    for parameter in parameters:
        names = set(parameter_instruments(parameter))
        touching = [g for g in groups if g[0] & names] if names else [g for g in groups if not g[0]]
        merged = [set(names), [parameter]]
        for group in touching:
            groups.remove(group)
            merged[0] |= group[0]
            merged[1] = group[1] + merged[1]
        groups.append(merged)
    return [(names, members) for names, members in groups]


def _poll_parameters(parameters):
    """Reads every monitored parameter, one after the other (in a gateway thread).

    Returns a list of (parameter key, reading dict or None, error text); a parameter that fails is
    reported on its own and does not stop the others.
    """
    results = []
    for parameter in parameters:
        try:
            results.append((id(parameter), read_for_monitor(parameter), ""))
        except Exception as e:
            results.append((id(parameter), None, f"{type(e).__name__}: {e}"))
    return results


class MonitorTab(QObject):
    """Live monitor. The monitored parameters are kept in ``station._monitor_parameters`` (the
    list QCoDeS' own monitor uses, which the station also prunes when an instrument is closed);
    values are read and described through ``qcodes.monitor``.

    Left: the table (value, last update and a "show time trace" checkbox per parameter).
    Right: a box with the time traces of the ticked parameters, two per row."""

    traces_updated = pyqtSignal()  # the traces were redrawn: the status bar sparklines follow

    def __init__(self, tab_widget, services):
        super().__init__()  # a QObject, so the polling results are delivered in the GUI thread
        self.tab = tab_widget
        self.services = services
        self._history = {}      # id(parameter) -> deque of (epoch seconds, numeric value)
        self._rows = {}         # id(parameter) -> row widgets
        self._traces = {}       # id(parameter) -> TimeTrace
        self._show_trace = {}   # id(parameter) -> bool (the checkbox, kept when the table is rebuilt)
        self._numeric = {}      # id(parameter) -> False once a reading was not a number
        self._units = {}        # id(parameter) -> unit of the last reading
        self._last_text = {}    # id(parameter) -> last displayed reading
        self._last_time = {}    # id(parameter) -> time of that reading
        self._window_s = DEFAULT_WINDOW_MIN * 60
        self._polling = False
        self._poll_left, self._poll_results = 0, []
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_timer)
        self._monitored_count = 0
        self.setup_ui()
        self._timer.start(DEFAULT_PERIOD_S * 1000)
        # the traces move along with the clock between two readings: on the shared 1 Hz tick while the tab is shown, every
        # HIDDEN_REDRAW_S while it is not (the sparklines of the status bar follow them)
        services.ticker.connect_visible(self.tab, self._redraw_traces, hidden_every=HIDDEN_REDRAW_S)
        # follow the services: what is monitored, the station and its instruments, the experiment parameters
        services.station.monitoredChanged.connect(self._on_monitored_changed)
        services.station.stationChanged.connect(self.sync)
        services.station.instrumentsChanged.connect(self.sync)
        services.registry.parametersChanged.connect(self.sync)
        services.run.monitorReadings.connect(self._on_run_readings)
        services.alarms.changed.connect(self._refresh_alarms)
        services.alarms.historyChanged.connect(self._refresh_alarms)
        self._refresh_alarms()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.tab.setLayout(layout)

        controls = QHBoxLayout()
        self.active_checkbox = QCheckBox("Monitoring")
        self.active_checkbox.setChecked(True)
        self.active_checkbox.setToolTip("Read the parameters periodically")
        controls.addWidget(self.active_checkbox)
        controls.addWidget(QLabel("every"))
        self.period_spin = QSpinBox()
        self.period_spin.setRange(MIN_PERIOD_S, MAX_PERIOD_S)
        self.period_spin.setValue(DEFAULT_PERIOD_S)
        self.period_spin.setSuffix(" s")
        self.period_spin.setToolTip("Refresh period in seconds (1 to 3600)")
        self.period_spin.valueChanged.connect(lambda seconds: self._timer.setInterval(seconds * 1000))
        self.period_spin.valueChanged.connect(self._publish_period)
        self.active_checkbox.toggled.connect(self._publish_period)
        controls.addWidget(self.period_spin)
        self.refresh_button = QPushButton("Refresh now")
        self.refresh_button.clicked.connect(lambda: self.poll())
        self.services.measuring.gate(self.refresh_button)  # the instruments are not read in parallel with a run
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)

        body = QHBoxLayout()
        layout.addLayout(body, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Stretch)  # long values are elided
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        body.addWidget(self.table, 2)

        # time traces box, to the right of the table
        self.traces_group = QGroupBox("Time traces")
        group_layout = QVBoxLayout(self.traces_group)
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Duration:"))
        self.window_spin = QSpinBox()
        self.window_spin.setRange(MIN_WINDOW_MIN, MAX_WINDOW_MIN)
        self.window_spin.setValue(DEFAULT_WINDOW_MIN)
        self.window_spin.setSuffix(" min")
        self.window_spin.setToolTip("Time shown by every trace, in minutes (1 to 1440); above 60 min the axis is in hours")
        self.window_spin.valueChanged.connect(self._on_window_changed)
        duration_row.addWidget(self.window_spin)
        self.window_label = QLabel("")
        duration_row.addWidget(self.window_label)
        duration_row.addStretch()
        group_layout.addLayout(duration_row)
        self.traces_hint = QLabel("Tick 'Show time trace' in the table to display a trace here.")
        self.traces_hint.setWordWrap(True)
        group_layout.addWidget(self.traces_hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.traces_container = QWidget()
        self.traces_layout = QGridLayout(self.traces_container)
        self.traces_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.traces_container)
        group_layout.addWidget(scroll, 1)
        right = QVBoxLayout()
        right.addWidget(self.traces_group, 3)
        right.addWidget(self._build_alarms_group(), 1)
        body.addLayout(right, 3)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self._update_status()

    # ----- the alarms of the session -----
    def _build_alarms_group(self):
        """Under the time traces: the alarms that went off in this session (shown once a parameter has an alarm)."""
        self.alarms_group = QGroupBox("Alarms")
        layout = QVBoxLayout(self.alarms_group)
        self.alarm_summary = QLabel("")
        self.alarm_summary.setWordWrap(True)
        layout.addWidget(self.alarm_summary)
        self.alarm_table = QTableWidget(0, 5)
        self.alarm_table.setHorizontalHeaderLabels(["Time", "Parameter", "Value", "Limit", "Action"])
        self.alarm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.alarm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alarm_table.verticalHeader().setVisible(False)
        header = self.alarm_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.alarm_table, 1)
        self.clear_alarms_button = QPushButton("Clear alarm history")
        self.clear_alarms_button.setToolTip("Empty this list. The warnings stay in the log file.")
        self.clear_alarms_button.clicked.connect(self.services.alarms.clear_history)
        layout.addWidget(self.clear_alarms_button, 0, Qt.AlignmentFlag.AlignLeft)
        return self.alarms_group

    def _refresh_alarms(self):
        alarms = self.services.alarms
        self.alarms_group.setVisible(bool(alarms.names()))
        self.alarm_summary.setText("Alarms on: " + ", ".join(alarms.names()) + f"  ({alarms.percent:g} % of the allowed values; "
                                   f"action: {ACTION_TEXT[self.services.settings.alarm_action]})")
        history = list(reversed(alarms.history))  # the latest first
        self.alarm_table.setRowCount(len(history))
        for row, record in enumerate(history):
            unit = f" {record['unit']}" if record["unit"] else ""
            for column, text in enumerate((datetime.fromtimestamp(record["time"]).strftime("%H:%M:%S"), record["name"],
                                           f"{record['value']:.4g}{unit}", record["limit"], ACTION_TEXT[record["action"]])):
                self.alarm_table.setItem(row, column, QTableWidgetItem(text))
        self.clear_alarms_button.setEnabled(bool(history))

    # ----- the monitored list (in the station service) -----
    def _monitored(self):
        return self.services.station.monitored()

    def _publish_period(self, *_):
        """Tell the measurement how often to update the monitor, and whether to."""
        station = self.services.station
        station.monitor_period = float(self.period_spin.value())
        station.monitor_active = self.active_checkbox.isChecked()

    def _poll_set(self):
        """What one reading covers: the monitored parameters, and the ones with an alarm that are not monitored."""
        monitored = self._monitored()
        return monitored + [p for p in self.services.alarms.parameters() if not any(p is m for m in monitored)]

    def is_monitored(self, parameter):
        return self.services.station.is_monitored(parameter)

    def add_parameter(self, parameter):
        """Monitor ``parameter`` (a no-op if it already is); it is read right away."""
        self.services.station.add_monitored(parameter)

    def remove_parameter(self, parameter):
        self.services.station.remove_monitored(parameter)

    def _on_monitored_changed(self):
        """The list changed (here or in another tab): rebuild the table, and read what was added right away."""
        grew = len(self._monitored()) > self._monitored_count
        self.sync()
        if grew:
            self.poll()

    def sync(self):
        """Rebuild the table and the traces from the station's list (also called when instruments change)."""
        parameters = self._monitored()
        self._monitored_count = len(parameters)
        keys = {id(p) for p in parameters}
        for store in (self._history, self._show_trace, self._numeric, self._units, self._last_text, self._last_time):
            for key in [k for k in store if k not in keys]:
                del store[key]
        for key in [k for k in self._traces if k not in keys]:
            self.traces_layout.removeWidget(self._traces[key])
            self._traces.pop(key).deleteLater()

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._rows = {}
        self.table.setRowCount(len(parameters))
        for row, parameter in enumerate(parameters):
            key = id(parameter)
            self._history.setdefault(key, deque(maxlen=MAX_POINTS))
            name_item = QTableWidgetItem(parameter.full_name)
            name_item.setToolTip(parameter_label(parameter) or parameter.full_name)
            self.table.setItem(row, COL_NAME, name_item)
            value_item = QTableWidgetItem(self._last_text.get(key, "—"))
            time_item = QTableWidgetItem(self._last_time.get(key, ""))
            self.table.setItem(row, COL_VALUE, value_item)
            self.table.setItem(row, COL_TIME, time_item)
            trace_item = QTableWidgetItem("")
            numeric = self._numeric.get(key, True)
            trace_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled if numeric
                                else Qt.ItemFlag.NoItemFlags)
            trace_item.setCheckState(Qt.CheckState.Checked if self._show_trace.setdefault(key, True) and numeric
                                     else Qt.CheckState.Unchecked)
            if not numeric:
                trace_item.setToolTip("Not a numeric value: no time trace")
            self.table.setItem(row, COL_TRACE, trace_item)
            remove_button = QPushButton("✕")
            remove_button.setMaximumWidth(30)
            remove_button.clicked.connect(lambda _=False, p=parameter: self.remove_parameter(p))
            self.table.setCellWidget(row, COL_REMOVE, remove_button)
            self._rows[key] = {"parameter": parameter, "value": value_item, "time": time_item, "trace": trace_item}
            if key not in self._traces:
                self._traces[key] = TimeTrace()
        self.table.blockSignals(False)
        self._refresh_traces()
        self._update_status()

    def _update_status(self, text=None):
        if text is not None:
            self.status_label.setText(text)
        elif not self._monitored():
            self.status_label.setText("Nothing monitored yet: right-click a parameter in the Parameter inspector and choose Monitor.")
        else:
            self.status_label.setText(f"{len(self._monitored())} parameters monitored.")

    # ----- time traces -----
    def _on_item_changed(self, item):
        if item.column() != COL_TRACE:
            return
        name = self.table.item(item.row(), COL_NAME).text()
        for key, row in self._rows.items():
            if row["parameter"].full_name == name:
                self._show_trace[key] = item.checkState() == Qt.CheckState.Checked
        self._refresh_traces()

    def shown_traces(self):
        """Time traces of the ticked parameters, in table order."""
        shown = []
        for parameter in self._monitored():
            key = id(parameter)
            if self._show_trace.get(key, True) and self._numeric.get(key, True) and key in self._traces:
                shown.append(self._traces[key])
        return shown

    def _refresh_traces(self):
        """Lay the ticked traces out two per row in the box on the right."""
        for trace in self._traces.values():
            self.traces_layout.removeWidget(trace)
            trace.hide()
        shown = self.shown_traces()
        for index, trace in enumerate(shown):
            self.traces_layout.addWidget(trace, index // TRACES_PER_ROW, index % TRACES_PER_ROW)
            trace.show()
        self.traces_hint.setVisible(not shown)
        self._redraw_traces()

    def _on_window_changed(self, minutes):
        self._window_s = minutes * 60
        hours, rest = divmod(minutes, 60)
        self.window_label.setText(f"= {hours} h" + (f" {rest} min" if rest else "") if minutes > 60 else "")
        self._redraw_traces()

    def _redraw_traces(self):
        for parameter in self._monitored():
            key = id(parameter)
            trace = self._traces.get(key)
            if trace is not None:
                trace.set_series(parameter.full_name, self._units.get(key, ""), self._history.get(key, ()), self._window_s)
        self.traces_updated.emit()

    def sparkline_series(self, window_s, maximum):
        """[(name, unit, [(epoch seconds, value)], slot)] of the first ``maximum`` parameters whose time trace is
        ticked, in table order, with the points of the last ``window_s`` seconds. ``slot`` is the place of the
        parameter in the table: it gives the parameter its colour."""
        now, series = time.time(), []
        for slot, parameter in enumerate(self._monitored()):
            key = id(parameter)
            if not (self._show_trace.get(key, True) and self._numeric.get(key, True)):
                continue
            points = []
            for point in reversed(self._history.get(key, ())):
                if now - point[0] > window_s:
                    break
                points.append(point)
            series.append((parameter.full_name, self._units.get(key, ""), points[::-1], slot))
            if len(series) >= maximum:
                break
        return series

    @staticmethod
    def _prune_history(history, now):
        """Keep the longest selectable duration (24 h), so the trace can be widened afterwards."""
        while history and now - history[0][0] > MAX_WINDOW_S + 60:
            history.popleft()

    # ----- polling -----
    def _on_timer(self):
        if self.active_checkbox.isChecked():
            self.poll(background=True)

    def poll(self, background=False):
        """Read all monitored parameters (through the instrument gateway), the instruments that are independent of each
        other at the same time, one gateway job per group of instruments. The periodic reads are background jobs: an
        instrument in use (a measurement, a ramp) is skipped and read at the next tick."""
        parameters = self._poll_set()
        if not parameters or self._polling:
            return
        gateway = self.services.gateway
        results_left = 0
        for names, group in instrument_groups(parameters):
            job = gateway.submit(_poll_parameters, group, kind=BACKGROUND if background else USER, instruments=names,
                                 label="Reading the monitored parameters")
            if job is None:
                continue  # that group is in use: it is read at the next tick (or the refusal is shown below)
            results_left += 1
            job.signals.result.connect(self._on_group_polled)
            job.signals.error.connect(self._on_poll_error)
        if results_left == 0:
            if gateway.run_active():
                self._update_status("A measurement is running: the instruments are not read in parallel, the measurement "
                                    "updates the monitor itself, at most once per period.")
            elif not background:
                self._update_status(gateway.last_refusal)
            return
        self._polling, self._poll_left, self._poll_results = True, results_left, []

    def _on_poll_error(self, error):
        self._update_status(f"Could not read the monitored parameters: {error[1]}")
        self._group_done([])

    def _on_group_polled(self, results):
        self._group_done(results)

    def _group_done(self, results):
        """One group of instruments has been read: when all have, show the readings together."""
        self._poll_results.extend(results)
        self._poll_left -= 1
        if self._poll_left <= 0:
            self._polling = False
            if self._poll_results:
                self._apply_results(self._poll_results)

    def _on_run_readings(self, results):
        """Readings the running measurement took for the monitored parameters (see ``RunController._feed_monitor``)."""
        self._apply_results(results, during_run=True)

    def _apply_results(self, results, during_run=False):
        errors = []
        numeric_changed = False
        alarm_pairs = []
        for key, reading, error in results:
            row = self._rows.get(key)
            if reading is not None and reading["numeric"] is not None:  # the alarms see every reading
                watched = row["parameter"] if row is not None else self.services.alarms.by_id(key)
                if watched is not None:
                    alarm_pairs.append((watched, reading["numeric"]))
            if row is None:  # removed in the meantime
                continue
            parameter = row["parameter"]
            if error:
                row["value"].setText("error")
                row["value"].setToolTip(error)
                errors.append(f"{parameter.full_name}: {error}")
                continue
            unit = f" {reading['unit']}" if reading["unit"] else ""
            self._units[key] = reading["unit"]
            self._last_text[key] = reading["text"] + unit
            self._last_time[key] = datetime.fromtimestamp(reading["ts"]).strftime("%H:%M:%S")
            row["value"].setText(self._last_text[key])
            row["value"].setToolTip(self._last_text[key])
            row["time"].setText(self._last_time[key])
            if reading["numeric"] is None:
                if self._numeric.get(key, True):
                    self._numeric[key] = False
                    numeric_changed = True
                continue
            history = self._history.setdefault(key, deque(maxlen=MAX_POINTS))
            history.append((reading["ts"], reading["numeric"]))
            self._prune_history(history, time.time())
        if numeric_changed:
            self.sync()  # disables the trace checkbox of the non-numeric parameter
        self.services.alarms.check_values(alarm_pairs)
        alive = set()
        for key, reading, error in results:  # an instrument that answered is alive: the health check need not ask
            row = self._rows.get(key)
            if row is not None and reading is not None and not error:
                alive |= set(parameter_instruments(row["parameter"]))
        if alive:
            self.services.station.instrumentsAlive.emit(alive)
        self._redraw_traces()
        if errors:
            self._update_status("Could not read: " + "; ".join(errors))
        else:
            self._update_status(f"{len(results)} parameters read at {datetime.now():%H:%M:%S}"
                                + (" by the measurement." if during_run else "."))

    # ----- context menu -----
    def _show_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None:
            return
        name = self.table.item(item.row(), COL_NAME).text()
        row = next((r for r in self._rows.values() if r["parameter"].full_name == name), None)
        if row is None:
            return
        menu = QMenu(self.table)
        menu.addAction("Remove from monitor").triggered.connect(lambda: self.remove_parameter(row["parameter"]))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def register_session_fields(self, fields):
        """The entries of this tab that are remembered between sessions."""
        fields.register("monitor/active", self.active_checkbox.isChecked, self.active_checkbox.setChecked)
        fields.register("monitor/period", self.period_spin.value, self.period_spin.setValue)
        fields.register("monitor/window_minutes", self.window_spin.value, self.window_spin.setValue)

    def shutdown(self):
        self._timer.stop()
