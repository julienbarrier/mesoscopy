"""The Settings window: default folders, the last station, QCoDeS configuration values and the saved layout."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from mesoscopy.core import qcodes_options as options
from mesoscopy.core.app_settings import FOLDER_KINDS


class SettingsDialog(QDialog):
    """Edits the application settings. Nothing is changed until OK or Apply."""

    FOLDER_LABELS = {"station": "Station folder", "database": "Database folder", "logs": "Logs folder"}

    def __init__(self, parent, settings, save_session):
        """``save_session`` is a function that remembers the layout and the fields now (the "Save layout" button)."""
        super().__init__(parent)
        self.settings = settings
        self._save_session = save_session
        self.setWindowTitle("Settings")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._folders_page(), "Folders")
        self.tabs.addTab(self._station_page(), "Station")
        self.tabs.addTab(self._measurement_page(), "Measurement")
        self.tabs.addTab(self._alarms_page(), "Alarms")
        self.tabs.addTab(self._status_bar_page(), "Status bar")
        self._qcodes_index = self.tabs.addTab(self._qcodes_page(), "QCoDeS")
        self.tabs.addTab(self._layout_page(), "Layout")
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c00;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        layout.addWidget(buttons)

    # ================= pages =================
    @staticmethod
    def _note(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: gray; font-size: 0.9em;")
        return label

    def _folders_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._note(
            "Default folders are offered when the application starts and by the Browse buttons. A folder "
            "remembered from the previous session takes their place when the layout is restored (Layout tab)."
        ))
        form = QFormLayout()
        layout.addLayout(form)
        self.folder_edits = {}
        for kind in FOLDER_KINDS:
            edit = QLineEdit(self.settings.default_folder(kind))
            edit.setPlaceholderText("none")
            browse = QPushButton("Browse...")
            browse.clicked.connect(lambda _=False, e=edit, k=kind: self._browse(e, k))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(browse)
            form.addRow(self.FOLDER_LABELS[kind] + ":", row)
            self.folder_edits[kind] = edit
        layout.addStretch()
        return page

    def _browse(self, edit, kind):
        folder = QFileDialog.getExistingDirectory(self, f"Default {kind} folder", edit.text() or os.path.expanduser("~"))
        if folder:
            edit.setText(folder)

    def _station_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.load_last_check = QCheckBox("Auto load station: load the last station when the program starts")
        self.load_last_check.setChecked(self.settings.load_last_station)
        layout.addWidget(self.load_last_check)
        layout.addWidget(self._note("Loading a station only reads its file: the instruments are connected when you "
                                    "load them in the Instruments tab."))
        row = QHBoxLayout()
        self.last_station_label = QLabel(self.settings.last_station or "No station loaded yet")
        self.last_station_label.setWordWrap(True)
        forget = QPushButton("Forget")
        forget.clicked.connect(self._forget_station)
        row.addWidget(QLabel("Last station:"))
        row.addWidget(self.last_station_label, 1)
        row.addWidget(forget)
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _forget_station(self):
        self.settings.last_station = ""
        self.last_station_label.setText("No station loaded yet")

    def _measurement_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        layout.addLayout(form)
        self.breakout_combo = QComboBox()
        self.breakout_combo.addItem("Any of them is true (OR)", "any")
        self.breakout_combo.addItem("All of them are true at the same time (AND)", "all")
        self.breakout_combo.setCurrentIndex(self.breakout_combo.findData(self.settings.breakout_mode))
        form.addRow("With several breakout conditions, stop when:", self.breakout_combo)
        self.threads_check = QCheckBox("Use threads: read the measured parameters of different instruments in parallel")
        self.threads_check.setChecked(options.effective_use_threads(self.settings))
        self.threads_check.setToolTip(
            "Passed to dond only (use_threads). The parameters of one instrument are still read one after the "
            "other. On by default; if your QCoDeS configuration file sets dataset.use_threads, that is the default."
        )
        form.addRow(self.threads_check)
        self.ramp_on_error_check = QCheckBox("After a measurement fails, ramp the experiment parameters it changed to 0")
        self.ramp_on_error_check.setChecked(self.settings.ramp_on_error)
        self.ramp_on_error_check.setToolTip(
            "A driver error ends the measurement. This brings the settable experiment parameters that the application "
            "has changed (and that are not at 0) to 0 at their maximum ramp rate. An instrument that does not answer "
            "is reported, the others are ramped. Parameters that were never changed are left alone.")
        form.addRow(self.ramp_on_error_check)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 100)
        self.retry_spin.setSuffix(" retries")
        self.retry_spin.setValue(self.settings.retry_attempts)
        self.retry_spin.setToolTip(
            "When an instrument does not answer during a measurement (a VISA timeout, a lost connection), the read or "
            "set is tried again this many times before the measurement fails. The clocks stand still meanwhile and "
            "Stop ends the wait. 0: no retry.")
        form.addRow("When an instrument does not answer:", self.retry_spin)
        self.retry_wait_spin = QDoubleSpinBox()
        self.retry_wait_spin.setRange(0.0, 3600.0)
        self.retry_wait_spin.setDecimals(1)
        self.retry_wait_spin.setSuffix(" s")
        self.retry_wait_spin.setValue(self.settings.retry_wait_s)
        self.retry_wait_spin.setToolTip("Wait before the first retry; the n-th retry waits n times as long.")
        form.addRow("Wait before retrying:", self.retry_wait_spin)
        self.past_cache_spin = QSpinBox()
        self.past_cache_spin.setRange(16, 8192)
        self.past_cache_spin.setSingleStep(64)
        self.past_cache_spin.setSuffix(" MB")
        self.past_cache_spin.setValue(self.settings.past_cache_mb)
        self.past_cache_spin.setToolTip(
            "The live plot keeps the earlier runs it draws faded behind the current curve in memory, up to this size "
            "(the oldest are dropped first). 256 MB is about 150 runs of 100 000 points. A smaller value saves "
            "memory, a larger one avoids reading runs again. On a 16 GB computer, keep it at 256 to 1024 MB.")
        form.addRow("Live plot, memory for earlier runs:", self.past_cache_spin)
        layout.addWidget(self._note(
            "Breakout conditions are defined on experiment parameters in the Parameter explorer and used by the "
            "\"Stop on breakout conditions\" box of the Measurement tab. A parameter that cannot be read stops the "
            "measurement in both modes. The choice applies to the next measurement."
        ))
        layout.addStretch()
        return page

    def _alarms_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        layout.addLayout(form)
        self.alarm_percent_spin = QSpinBox()
        self.alarm_percent_spin.setRange(1, 100)
        self.alarm_percent_spin.setSuffix(" % of allowed values")
        self.alarm_percent_spin.setValue(int(round(self.settings.alarm_percent)))
        self.alarm_percent_spin.setToolTip("An alarm goes off when the value reaches this part of the allowed values.")
        form.addRow("Raise an alarm at:", self.alarm_percent_spin)
        self.alarm_action_combo = QComboBox()
        self.alarm_action_combo.addItem("Only show a message in the status bar", "message")
        self.alarm_action_combo.addItem("Pause the measurement", "pause")
        self.alarm_action_combo.addItem("Stop the measurement", "stop")
        self.alarm_action_combo.addItem("Stop the measurement and ramp to 0", "stop_ramp")
        self.alarm_action_combo.setCurrentIndex(self.alarm_action_combo.findData(self.settings.alarm_action))
        form.addRow("When an alarm goes off:", self.alarm_action_combo)
        layout.addWidget(self._note(
            "Alarms are put on parameters in the Parameter explorer (right-click, Add alarm). The allowed values are the "
            "limits of the parameter. If they are symmetric about 0 the alarm goes off at |value| = the percentage of the "
            "limit; if not, each side has its own limit (the positive side at the percentage of the allowed maximum, the "
            "negative side at the percentage of the allowed minimum). Whatever the action, the alarm is shown in the "
            "status bar (click it to open the Monitor tab), kept in the list of the Monitor tab for this session, and "
            "written to the log as a WARNING when the logging is running. Pausing takes effect after the current "
            "point. The choice applies at once."
        ))
        layout.addStretch()
        return page

    def _status_bar_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.sparklines_check = QCheckBox("Show sparklines in the status bar")
        self.sparklines_check.setChecked(self.settings.show_sparklines)
        layout.addWidget(self.sparklines_check)
        layout.addWidget(self._note(
            "The sparklines follow the Monitor tab: the monitored parameters whose \"Show time trace\" box is "
            "ticked, in the order of the table. They have no axis; hover one to see its last value and range."
        ))
        form = QFormLayout()
        layout.addLayout(form)
        self.sparkline_max_spin = QSpinBox()
        self.sparkline_max_spin.setRange(1, 12)
        self.sparkline_max_spin.setValue(self.settings.sparkline_max)
        self.sparkline_max_spin.setToolTip("Most sparklines shown at once (the status bar has limited room)")
        form.addRow("Maximum number of sparklines:", self.sparkline_max_spin)
        self.sparkline_minutes_spin = QSpinBox()
        self.sparkline_minutes_spin.setRange(1, 1440)
        self.sparkline_minutes_spin.setSuffix(" min")
        self.sparkline_minutes_spin.setValue(self.settings.sparkline_minutes)
        self.sparkline_minutes_spin.setToolTip("Time shown by every sparkline, in minutes (1 to 1440)")
        form.addRow("Duration shown:", self.sparkline_minutes_spin)
        layout.addStretch()
        return page

    def _qcodes_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._note(
            f"QCoDeS configuration values, applied now and at each start. Your QCoDeS configuration file is not "
            f"modified ({options.qc.config.current_config_path})."
        ))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.option_widgets = {}
        for option in options.OPTIONS:
            widget = self._option_widget(option)
            reset = QPushButton("Default")
            reset.setToolTip(f"Back to the QCoDeS default: {options.default_value(option.key)!r}")
            reset.clicked.connect(lambda _=False, o=option: self._set_widget(o, options.default_value(o.key)))
            row = QHBoxLayout()
            row.addWidget(widget, 1)
            row.addWidget(reset)
            label = QLabel(option.label + ":")
            label.setToolTip(option.help)
            widget.setToolTip(option.help)
            form.addRow(label, row)
            self.option_widgets[option.key] = widget
            self._set_widget(option, options.get_value(option.key))
        return page

    @staticmethod
    def _option_widget(option):
        if option.kind == "bool":
            return QCheckBox()
        if option.kind == "choice":
            combo = QComboBox()
            combo.addItems(option.choices)
            return combo
        if option.kind == "number":
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(2)
            return spin
        return QLineEdit()

    def _set_widget(self, option, value):
        widget = self.option_widgets[option.key]
        if option.kind == "bool":
            widget.setChecked(bool(value))
        elif option.kind == "choice":
            widget.setCurrentText(options.NONE_CHOICE if value is None else str(value))
        elif option.kind == "number":
            widget.setValue(float(value))
        else:
            widget.setText("" if value is None else str(value))

    def _widget_value(self, option):
        widget = self.option_widgets[option.key]
        if option.kind == "bool":
            return widget.isChecked()
        if option.kind == "choice":
            text = widget.currentText()
            return None if text == options.NONE_CHOICE else text
        if option.kind == "number":
            return widget.value()
        return widget.text()

    def _layout_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.restore_check = QCheckBox("Restore the window layout and the field entries when the application starts")
        self.restore_check.setChecked(self.settings.restore_session)
        layout.addWidget(self.restore_check)
        layout.addWidget(self._note(
            "Remembered when the window closes: its size and position, the selected tab, the folders, the station "
            "file, the sample name, the Measurement tab (names, sweeps, measured parameters; the parameters are "
            "selected again once their instruments are loaded) and the Monitor and live plot settings."
        ))
        row = QHBoxLayout()
        save = QPushButton("Save layout now")
        save.clicked.connect(self._save_now)
        forget = QPushButton("Forget saved layout")
        forget.clicked.connect(self._forget_layout)
        row.addWidget(save)
        row.addWidget(forget)
        row.addStretch()
        layout.addLayout(row)
        self.layout_message = QLabel("")
        layout.addWidget(self.layout_message)
        where = QLabel(f"Settings are stored in: {self.settings.file_name()}")
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(where)
        layout.addStretch()
        return page

    def _save_now(self):
        self._save_session()
        self.layout_message.setText("Layout saved.")

    def _forget_layout(self):
        self.settings.clear_session()
        self.layout_message.setText("Saved layout forgotten.")

    # ================= applying =================
    def apply(self):
        """Store and apply every setting. Returns True if all could be applied."""
        self.error_label.setText("")
        for kind, edit in self.folder_edits.items():
            folder = edit.text().strip()
            if folder and not os.path.isdir(folder):
                self.error_label.setText(f"{self.FOLDER_LABELS[kind]}: '{folder}' is not a folder.")
                self.tabs.setCurrentIndex(0)
                return False
        for kind, edit in self.folder_edits.items():
            self.settings.set_default_folder(kind, edit.text().strip())
        self.settings.load_last_station = self.load_last_check.isChecked()
        self.settings.restore_session = self.restore_check.isChecked()
        self.settings.breakout_mode = self.breakout_combo.currentData()
        # remembered only when it differs from the default, so that the default (and the QCoDeS file) keeps applying
        use_threads = self.threads_check.isChecked()
        self.settings.use_threads = None if use_threads == options.default_use_threads() else use_threads
        self.settings.past_cache_mb = self.past_cache_spin.value()
        self.settings.ramp_on_error = self.ramp_on_error_check.isChecked()
        self.settings.retry_attempts = self.retry_spin.value()
        self.settings.retry_wait_s = self.retry_wait_spin.value()
        self.settings.alarm_percent = self.alarm_percent_spin.value()
        self.settings.alarm_action = self.alarm_action_combo.currentData()
        self.settings.show_sparklines = self.sparklines_check.isChecked()
        self.settings.sparkline_max = self.sparkline_max_spin.value()
        self.settings.sparkline_minutes = self.sparkline_minutes_spin.value()

        overrides, problems = dict(self.settings.qcodes_overrides()), []
        for option in options.OPTIONS:
            value = self._widget_value(option)
            if value == options.get_value(option.key) and option.key not in overrides:
                continue
            try:
                options.set_value(option.key, value)
            except Exception as e:
                problems.append(f"{option.label}: {e}")
                continue
            if value == options.default_value(option.key):
                overrides.pop(option.key, None)  # back to the default: nothing to remember
            else:
                overrides[option.key] = value
        self.settings.set_qcodes_overrides(overrides)
        self.settings.notify_changed()  # what depends on the settings (sparklines, breakout tooltip) updates itself
        if problems:
            self.error_label.setText("\n".join(problems))
            self.tabs.setCurrentIndex(self._qcodes_index)
            return False
        return True

    def _ok(self):
        if self.apply():
            self.accept()
