"""The main window: the composition root of the application.

It builds the services (``mesoscopy.services``), the tabs and the snapshot loader, and connects them: tabs and
services talk through signals, never through each other or through this window. What remains here is what only a
window can do: the menu bar, the status bar, the tabs' frame, remembering the layout and closing.
"""
from PyQt6.QtCore import QByteArray, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QLabel, QMainWindow, QMessageBox, QStatusBar, QTabWidget, QVBoxLayout, QWidget

from mesoscopy.core.constants import CONTENT_MARGINS
from mesoscopy.core.qcodes_options import apply_overrides
from mesoscopy.services import create_services
from mesoscopy.services.run_queue import QueueHooks
from mesoscopy.ui.about_dialog import AboutDialog
from mesoscopy.ui.session import SessionFields
from mesoscopy.ui.settings_dialog import SettingsDialog
from mesoscopy.ui.snapshot_loader import LoaderHooks, SnapshotLoader
from mesoscopy.ui.tabs.data_tab import DataTab
from mesoscopy.ui.tabs.instruments_tab import InstrumentsTab
from mesoscopy.ui.tabs.monitor_tab import MonitorTab
from mesoscopy.ui.tabs.parameter_explorer_tab import ParameterExplorerTab
from mesoscopy.ui.tabs.queue_tab import QueueTab
from mesoscopy.ui.tabs.sparklines import StatusSparklines
from mesoscopy.ui.tabs.sweep_tab import SweepTab


ALARM_SHOWN_MS = 15000  # how long an alarm stays in the status bar


class AlarmLabel(QLabel):
    """The alarm in the status bar: red, hidden after a while, and a click goes to the Monitor tab."""

    clicked = pyqtSignal()

    def __init__(self):
        super().__init__("")
        self.setStyleSheet("color: white; background: #c62828; font-weight: bold; padding: 1px 8px; border-radius: 3px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_alarm(self, text, tooltip):
        self.setText("\u26A0 " + text)
        self.setToolTip(tooltip + "\nClick to open the Monitor tab.")
        self.setVisible(True)
        self._timer.start(ALARM_SHOWN_MS)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle("mesoscoPy - Experiment Runner")
        self.setStatusBar(QStatusBar(self))

        # the services every tab works with: settings, instrument gateway, station, experiment parameters, data
        # location, run controller
        self.services = services = create_services(settings, parent=self)
        services.status.message.connect(lambda text, timeout: self.statusBar().showMessage(text, timeout))
        # the experiment parameters follow the instruments (connected before the tabs, which subscribe to the result)
        services.station.instrumentsChanged.connect(services.registry.sync)

        # what the user is waiting for, when instruments are in use
        self.busy_label = QLabel("")
        self.statusBar().addPermanentWidget(self.busy_label)
        # an alarm on a parameter: shown for a while in the status bar; a click opens the Monitor tab
        self.alarm_label = AlarmLabel()
        self.statusBar().addPermanentWidget(self.alarm_label)
        services.alarms.alarmRaised.connect(self._show_alarm)
        self.alarm_label.clicked.connect(self._open_monitor)
        services.gateway.changed.connect(self._show_gateway_state)

        self.tabs = QTabWidget()
        self.instruments_tab_widget = QWidget()
        self.data_tab_widget = QWidget()
        self.sweep_tab_widget = QWidget()
        self.parameter_explorer_widget = QWidget()
        self.queue_widget = QWidget()
        self.monitor_widget = QWidget()
        self.tabs.addTab(self.data_tab_widget, "Data")
        self.tabs.addTab(self.instruments_tab_widget, "Instruments")
        self.tabs.addTab(self.parameter_explorer_widget, "Parameter explorer")
        self.tabs.addTab(self.sweep_tab_widget, "Measurement")
        self.tabs.addTab(self.queue_widget, "Queue")
        self.tabs.addTab(self.monitor_widget, "Monitor")

        wrapper = QWidget()  # the tabs with a margin around
        wrapper_layout = QVBoxLayout()
        wrapper_layout.setContentsMargins(CONTENT_MARGINS, CONTENT_MARGINS, CONTENT_MARGINS, CONTENT_MARGINS)
        wrapper_layout.addWidget(self.tabs)
        wrapper.setLayout(wrapper_layout)
        self.setCentralWidget(wrapper)

        # the tabs: each owns its widgets and gets the services, nothing else
        self.instruments_tab = InstrumentsTab(self.instruments_tab_widget, services)
        self.data_tab = DataTab(self.data_tab_widget, services)
        self.sweep_tab = SweepTab(self.sweep_tab_widget, services)
        self.parameter_explorer_tab = ParameterExplorerTab(self.parameter_explorer_widget, services)
        self.queue_tab = QueueTab(self.queue_widget, services)
        self.monitor_tab = MonitorTab(self.monitor_widget, services)
        # the queue takes recipes into the Measurement tab and runs what it builds; editing shows that tab
        services.queue.hooks = QueueHooks(apply_state=self.sweep_tab.set_state, build_request=self.sweep_tab.build_request)
        services.queue.editRequested.connect(lambda _item: self.tabs.setCurrentWidget(self.sweep_tab_widget))

        # the monitored parameters whose trace is ticked, as sparklines in the status bar
        self.sparklines = StatusSparklines(services.settings, self.monitor_tab.sparkline_series)
        self.statusBar().addPermanentWidget(self.sparklines)
        self.monitor_tab.traces_updated.connect(self.sparklines.refresh)

        # Load Snapshot sets several tabs up: it is given what it needs, and is started by signals of the tabs
        self.snapshot_loader = SnapshotLoader(services, LoaderHooks(
            parent=self, instrument_manager=self.instruments_tab.manager,
            apply_sweep_state=self.sweep_tab.set_state,
            show_measurement_tab=lambda: self.tabs.setCurrentWidget(self.sweep_tab_widget),
        ))
        self.data_tab.loadSnapshotRequested.connect(self.snapshot_loader.load)
        self.instruments_tab.saveStateRequested.connect(self.snapshot_loader.save_instrument_state)
        self.instruments_tab.restoreFromFileRequested.connect(self.snapshot_loader.restore_instrument_from_file)
        self.instruments_tab.restoreFromRunRequested.connect(self.snapshot_loader.restore_instrument_from_run)

        self._build_menus()
        self._register_session_fields()
        # the tabs open up as the application is set up: a database, a station, experiment parameters, a monitor
        self._starting = True
        for signal in (services.data.entryChanged, services.station.stationChanged, services.station.instrumentsChanged,
                       services.station.monitoredChanged, services.registry.parametersChanged, services.alarms.changed):
            signal.connect(self.update_tab_access)
        self.update_tab_access()
        self._apply_startup_settings()
        self._starting = False
        self.update_tab_access()
        QTimer.singleShot(0, self._offer_queue_recovery)  # once the window is up

    # ================= which tabs can be used =================
    def tab_requirements(self):
        """[(tab widget, what is needed first, whether it is there)] in tab order. Every tab but Data needs a
        database; each of the others needs what comes before it in the set-up."""
        services = self.services
        registry = services.registry
        database = services.data.has_database
        instruments = database and bool(services.station.instruments())
        # the station-level parameters (elapsed time) are always there: they do not count
        parameters = instruments and any(registry.definitions[name].kind != "root" for name in registry.parameters())
        monitored = instruments and (bool(services.station.monitored()) or bool(services.alarms.parameters()))
        after_database = "Enter a database in the Data tab first."
        after_instrument = "Connect an instrument in the Instruments tab first." if database else after_database
        after_parameters = "Define experiment parameters in the Parameter explorer first." if instruments else after_instrument
        after_monitor = ("Monitor a parameter, or put an alarm on one, from the Parameter explorer first."
                         if instruments else after_instrument)
        return [
            (self.data_tab_widget, "", True),
            (self.instruments_tab_widget, after_database, database),
            (self.parameter_explorer_widget, after_instrument, instruments),
            (self.sweep_tab_widget, after_parameters, parameters),
            (self.queue_widget, after_parameters, parameters),
            (self.monitor_widget, after_monitor, monitored),
        ]

    def update_tab_access(self):
        """Grey out the tabs whose set-up step is not done yet (their tooltip says what is missing), and leave a tab
        that is no longer available."""
        enabled = []
        for widget, missing, available in self.tab_requirements():
            index = self.tabs.indexOf(widget)
            self.tabs.setTabEnabled(index, available)
            self.tabs.setTabToolTip(index, "" if available else missing)
            enabled.append(available)
        current = self.tabs.currentIndex()
        if not self._starting and not enabled[current]:  # at start the saved tab is kept until everything is loaded
            self.tabs.setCurrentIndex(max(i for i in range(current) if enabled[i]))

    # ================= menus, settings and session =================
    def _build_menus(self):
        """The menu bar: in the window on Windows and Linux, in the system menu bar on macOS, where the Settings
        entry is moved to the application menu (Preferences) by Qt."""
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("Settings...", self)
        settings_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        self.settings_action = settings_action
        # About: the system decides where it lives (the application menu on macOS, the Help menu elsewhere)
        about_action = QAction("About mesoscoPy", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.open_about)
        self.menuBar().addMenu("&Help").addAction(about_action)
        self.about_action = about_action

    def open_settings(self):
        """Open the Settings window."""
        SettingsDialog(self, self.services.settings, self.save_session).exec()

    def open_about(self):
        """Open the About window."""
        AboutDialog(self, self.services.settings.file_name()).exec()

    def _register_session_fields(self):
        """The window layout and the fields whose entries are remembered: each tab registers its own. The order is
        the order of restoring: a folder before the files it lists."""
        fields = self.session_fields = SessionFields()
        fields.register(
            "window/geometry", lambda: bytes(self.saveGeometry().toBase64()).decode(),
            lambda value: self.restoreGeometry(QByteArray.fromBase64(value.encode())),
        )
        for tab in (self.instruments_tab, self.data_tab, self.sweep_tab, self.queue_tab, self.monitor_tab):
            tab.register_session_fields(fields)
        fields.register("alarms/parameters", self.services.alarms.names, self.services.alarms.restore_names)
        fields.register("window/tab", self.tabs.currentIndex, self.tabs.setCurrentIndex)

    def save_session(self):
        """Remember the window layout and the field entries for the next session."""
        self.services.settings.save_session(self.session_fields.capture())

    def _apply_startup_settings(self):
        """At start: QCoDeS values chosen by the user, default folders, the previous session, the last station."""
        settings = self.services.settings
        apply_overrides(settings.qcodes_overrides())
        self.instruments_tab.apply_default_folders()
        self.data_tab.apply_default_folders()
        if settings.restore_session:
            self.session_fields.restore(settings.session())
        if settings.load_last_station:
            self.instruments_tab.load_last_station()

    def _offer_queue_recovery(self):
        """The last session ended while the queue was running (a crash, a power cut): offer to put the queue back."""
        queue = self.services.queue
        summary = queue.interrupted_summary()
        if summary is None:
            return
        done, total, title = summary
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Interrupted queue")
        box.setText(f"The last session ended while the queue was running: {done} of {total} items were finished"
                    + (f" and '{title}' was in progress." if title else "."))
        box.setInformativeText(
            "Restore the queue? Nothing starts by itself: load the station and the instruments, check them, then press "
            "Start in the Queue tab. The data the interrupted item had written stays in the database.")
        again = box.addButton("Restore, run the interrupted item again", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Restore, without the interrupted item", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (again, skip):
            queue.restore_after_crash(rerun_interrupted=clicked is again)
            self.tabs.setCurrentWidget(self.queue_widget) if self.tabs.isTabEnabled(self.tabs.indexOf(self.queue_widget)) else None
        else:
            queue.crash_data = None

    # ================= the window itself =================
    def _show_alarm(self, record):
        self.alarm_label.show_alarm(record["text"].replace("ALARM ", "", 1), record["text"])

    def _open_monitor(self):
        """A click on the alarm in the status bar: the Monitor tab, where the alarms of the session are listed."""
        if self.tabs.isTabEnabled(self.tabs.indexOf(self.monitor_widget)):
            self.tabs.setCurrentWidget(self.monitor_widget)

    def _show_gateway_state(self):
        """Show in the status bar the measurement or user action that has the instruments."""
        labels = self.services.gateway.labels()
        self.busy_label.setText("Instruments in use: " + "; ".join(labels) if labels else "")

    def closeEvent(self, event):
        """Remember the layout, stop a running measurement, then disconnect all loaded instruments."""
        self.save_session()
        self.services.queue.stop()  # no next item after the one in progress
        self.services.run.stop()  # also wakes a paused run
        self.sweep_tab.shutdown()
        self.monitor_tab.shutdown()
        self.parameter_explorer_tab.shutdown()
        self.services.gateway.shutdown()  # let the measurement and the other jobs end before the instruments are closed
        self.instruments_tab.shutdown()  # the experiment parameters the application changed go to 0 first
        self.services.queue.mark_clean()  # a clean end: the next start finds no interrupted queue
        super().closeEvent(event)
