"""Instruments tab UI components."""
from PyQt6.QtWidgets import (
    QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QSizePolicy, QListWidget,
    QComboBox, QLabel, QWidget, QMenu, QFileDialog,
)
import os

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from mesoscopy.ui.station_manager import StationManager
from mesoscopy.ui.tabs.instrument_detail import InstrumentDetailPanel
from mesoscopy.ui.tabs.instrument_status import InstrumentStatusDelegate
from mesoscopy.ui.tabs.ui_helpers import make_text_selectable, set_groupbox_title_bold

class InstrumentsTab(QObject):
    """Instruments tab: load a station and its instruments, and follow the connected ones.

    Instrument setup (presets and aliases) comes from the station file, not from this tab.
    """

    # the actions of the right-click menu that the snapshot loader carries out (the application connects them)
    saveStateRequested = pyqtSignal(str)
    restoreFromFileRequested = pyqtSignal(str)
    restoreFromRunRequested = pyqtSignal(str)

    def __init__(self, tab_widget, services):
        super().__init__()  # a QObject: it has signals
        self.tab = tab_widget
        self.services = services
        self.manager = StationManager(self, services)  # loads stations and instruments, fills the lists
        self.setup_ui()

    # ----- folders and files, for the session and the settings -----
    def _browse_station_folder(self):
        start = self.station_folder_display.text().strip() or self.services.settings.default_folder("station") or "./"
        folder = QFileDialog.getExistingDirectory(self.tab, "Select Station Folder", start)
        if folder:
            self.station_folder_display.setText(folder)
        return folder

    def select_station_folder(self):
        if self._browse_station_folder():
            self.manager.populate_station_files()

    def set_station_folder(self, folder):
        """Use ``folder`` as the station folder and list its station files (ignored if it is not a folder)."""
        if folder and os.path.isdir(folder):
            self.station_folder_display.setText(folder)
            self.manager.populate_station_files()

    def set_station_file(self, name):
        if name and self.station_file_combo.findText(name) >= 0:
            self.station_file_combo.setCurrentText(name)

    def apply_default_folders(self):
        self.set_station_folder(self.services.settings.default_folder("station"))

    def register_session_fields(self, fields):
        fields.register("instruments/station_folder", self.station_folder_display.text, self.set_station_folder)
        fields.register("instruments/station_file", self.station_file_combo.currentText, self.set_station_file)

    def load_last_station(self):
        """Load the station file used last (the Settings ask for it at start)."""
        last = self.services.settings.last_station
        if last and os.path.isfile(last):
            self.set_station_folder(os.path.dirname(last))
            self.set_station_file(os.path.basename(last))
            self.manager.load_station()

    def shutdown(self):
        self.instrument_detail.shutdown()
        self.manager.disconnect_all_instruments()

    def setup_ui(self):
        """Set up the instruments tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        # Left side - Station, Instruments, Logs
        instruments_left_widget = QWidget()
        instruments_left_widget.setMaximumWidth(280)
        instruments_left = QVBoxLayout()
        instruments_left_widget.setLayout(instruments_left)

        # Station group
        station_group = QGroupBox("Station")
        set_groupbox_title_bold(station_group)
        station_layout = QFormLayout()
        station_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        station_group.setLayout(station_layout)

        self.station_folder_display = QLineEdit()
        self.station_folder_display.setReadOnly(True)
        self.station_folder_display.setPlaceholderText("Station folder")
        self.station_folder_button = QPushButton("Browse...")
        self.station_folder_button.clicked.connect(self.select_station_folder)

        station_folder_layout = QHBoxLayout()
        station_folder_layout.addWidget(self.station_folder_display)
        station_folder_layout.addWidget(self.station_folder_button)

        self.station_file_combo = QComboBox()
        self.station_file_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.station_file_combo.setPlaceholderText("Station file")

        station_fields_layout = QVBoxLayout()
        station_fields_layout.setSpacing(0)
        station_fields_layout.addLayout(station_folder_layout)
        station_fields_layout.addWidget(self.station_file_combo)

        station_layout.addRow(station_fields_layout)

        self.load_station_button = QPushButton("Load Station")
        self.load_station_button.clicked.connect(self.manager.load_station)
        self.services.measuring.gate(self.load_station_button)  # refused while a measurement runs
        station_layout.addRow(self.load_station_button)

        self.station_error_display = make_text_selectable(QLabel(""))
        self.station_error_display.setWordWrap(True)
        self.station_error_display.setStyleSheet("color: #c00; font-size: 0.9em;")
        self.station_error_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        station_layout.addRow(self.station_error_display)

        instruments_left.addWidget(station_group)

        # Instruments group
        instr_group = QGroupBox("Instruments to Load")
        set_groupbox_title_bold(instr_group)
        instr_layout = QVBoxLayout()

        self.instr_list = QListWidget()
        self.instr_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        instr_layout.addWidget(self.instr_list)

        self.load_instr_button = QPushButton("Load Selected Instruments")
        self.load_instr_button.setEnabled(False)
        self.services.measuring.gate(self.load_instr_button)
        self.load_instr_button.clicked.connect(self.manager.load_selected_instruments)
        instr_layout.addWidget(self.load_instr_button)

        self.instr_error_display = make_text_selectable(QLabel(""))
        self.instr_error_display.setWordWrap(True)
        self.instr_error_display.setStyleSheet("color: #c00; font-size: 0.9em;")
        self.instr_error_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        instr_layout.addWidget(self.instr_error_display)

        instr_group.setLayout(instr_layout)
        instr_group.setMinimumHeight(500)
        instruments_left.addWidget(instr_group)

        # Second column - Connected instruments (all components of the loaded station)
        connected_widget = QWidget()
        connected_widget.setMaximumWidth(280)
        connected_widget.setVisible(False)  # shown once a station is loaded
        self.connected_widget = connected_widget
        connected_column = QVBoxLayout()
        connected_widget.setLayout(connected_column)

        connected_group = QGroupBox("Connected instruments")
        set_groupbox_title_bold(connected_group)
        connected_layout = QVBoxLayout()

        self.connected_instr_list = QListWidget()
        # one instrument at a time: the panel on the right follows the selected instrument
        self.connected_instr_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.connected_instr_list.setItemDelegate(
            InstrumentStatusDelegate(self.connected_instr_list)
        )
        self.connected_instr_list.setMouseTracking(True)  # hover tooltips
        self.connected_instr_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.connected_instr_list.customContextMenuRequested.connect(self._connected_context_menu)
        connected_layout.addWidget(self.connected_instr_list, 1)  # takes the height that is left

        self.update_snapshot_button = QPushButton("Update Snapshot of Selected")
        self.update_snapshot_button.setToolTip(
            "Read every parameter of the selected instruments again, so that the values QCoDeS keeps (and stores "
            "in the snapshot of the next run) include changes made outside the application."
        )
        self.update_snapshot_button.setEnabled(False)
        self.services.measuring.gate(self.update_snapshot_button)
        self.update_snapshot_button.clicked.connect(
            lambda: self.manager.update_selected_snapshots()
        )
        connected_layout.addWidget(self.update_snapshot_button)

        self.reconnect_instr_button = QPushButton("Reconnect Selected")
        self.reconnect_instr_button.setVisible(False)  # shown when an instrument stops responding
        self.services.measuring.gate(self.reconnect_instr_button)
        self.reconnect_instr_button.clicked.connect(self.manager.reconnect_selected_instruments)
        connected_layout.addWidget(self.reconnect_instr_button)

        self.disconnect_instr_button = QPushButton("Disconnect Selected")
        self.disconnect_instr_button.setEnabled(False)
        self.services.measuring.gate(self.disconnect_instr_button)
        self.disconnect_instr_button.clicked.connect(self.manager.disconnect_selected_instruments)
        connected_layout.addWidget(self.disconnect_instr_button)

        self.connected_error_display = make_text_selectable(QLabel(""))
        self.connected_error_display.setWordWrap(True)
        self.connected_error_display.setStyleSheet("color: #c00; font-size: 0.9em;")
        self.connected_error_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.connected_error_display.setVisible(False)  # only shown when there is an error
        connected_layout.addWidget(self.connected_error_display)

        connected_group.setLayout(connected_layout)
        connected_column.addWidget(connected_group)

        instruments_left.addStretch()

        main_layout.addWidget(instruments_left_widget)
        main_layout.addWidget(connected_widget)

        # Third column - command log / raw command / snapshot of the selected instrument, over the space that is left
        self.instrument_detail = InstrumentDetailPanel(self.services)
        self.connected_instr_list.itemSelectionChanged.connect(self._selection_changed)
        main_layout.addWidget(self.instrument_detail, 1)
        main_layout.addStretch(0)  # takes the space while the panel is hidden

    def _connected_context_menu(self, position):
        """Right click on a connected instrument: update its snapshot, save or restore its state, disconnect it."""
        item = self.connected_instr_list.itemAt(position)
        if item is None:
            return
        name = item.text()
        manager = self.manager
        menu = QMenu(self.connected_instr_list)
        actions = {}

        def add(text, tip, callback):
            action = menu.addAction(text)
            action.setToolTip(tip)
            self.services.measuring.block(action)  # every entry works on the instrument: not while a measurement runs
            actions[action] = callback

        add(f"Update snapshot of {name}", "Read every parameter of this instrument again (snapshot with update).",
            lambda: manager.update_snapshots([name]))
        menu.addSeparator()
        add(f"Save state of {name} to file...", "Read all its parameters, then save them (and its experiment "
            "parameters) as a JSON file.", lambda: self.saveStateRequested.emit(name))
        add(f"Restore state of {name} from file...", "Set its parameters and experiment parameters from a saved "
            "JSON file. You review the changes first.", lambda: self.restoreFromFileRequested.emit(name))
        add(f"Restore state of {name} from a run...", "Set its parameters and experiment parameters as they "
            "were in the snapshot of a run. You review the changes first.",
            lambda: self.restoreFromRunRequested.emit(name))
        menu.addSeparator()
        add(f"Disconnect {name}", "Close this instrument and remove it from the station.",
            lambda: manager.disconnect_instruments([name]))
        chosen = menu.exec(self.connected_instr_list.viewport().mapToGlobal(position))
        if chosen in actions:
            actions[chosen]()

    def _selection_changed(self):
        names = [item.text() for item in self.connected_instr_list.selectedItems()]
        self.instrument_detail.set_selection(names)
