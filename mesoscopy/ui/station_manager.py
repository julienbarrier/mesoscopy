"""Station and instrument management (UI adapter)."""
import os
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from mesoscopy.instrument.classification import classify_loaded_instruments
from mesoscopy.instrument.station_loader import get_instruments_from_yaml, load_station_from_config


class StationManager:
    """Manages station loading and instrument discovery (UI only)."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.station = None

    def populate_station_files(self):
        """Populate the station file dropdown with .station.yaml files from the selected folder."""
        self.main_window.station_file_combo.clear()

        folder = self.main_window.station_folder_display.text()
        if not folder or not os.path.isdir(folder):
            return

        station_files = [f for f in os.listdir(folder) if f.endswith('.station.yaml')]
        station_files.sort()

        if station_files:
            self.main_window.station_file_combo.addItems(station_files)
            if len(station_files) == 1:
                self.main_window.station_file_combo.setCurrentIndex(0)

    def load_station(self):
        """Load station from YAML configuration file."""
        try:
            config_file = self.main_window.station_file_combo.currentText()
            if not config_file:
                self.main_window.statusBar().showMessage("Please select a station file.", 2000)
                return False

            folder = self.main_window.station_folder_display.text()
            if folder:
                config_file = os.path.join(folder, config_file)

            self.station = load_station_from_config(config_file)
            self.main_window.station = self.station
            self.main_window.statusBar().showMessage("Station loaded successfully.", 2000)
            self.populate_instrument_list(config_file)
            self.main_window.parameters_tab.populate_instruments()
            self.populate_master_lockin_dropdown()
            return True
        except Exception as e:
            self.main_window.statusBar().showMessage(f"Error loading station: {e}")
            return False

    def populate_instrument_list(self, config_file=None):
        """Populate instrument list from station or YAML config file."""
        self.main_window.instr_list.clear()
        instr_names = []

        if config_file:
            instr_names = get_instruments_from_yaml(config_file)
        elif self.station and hasattr(self.station, 'config') and self.station.config:
            if hasattr(self.station.config, 'instrument_configs'):
                instr_names = list(self.station.config.instrument_configs.keys())
            elif hasattr(self.station.config, 'instruments'):
                instr_names = list(self.station.config.instruments.keys())

        for name in sorted(instr_names):
            item = QListWidgetItem(name)
            item.setSelected(True)
            self.main_window.instr_list.addItem(item)

        if instr_names:
            self.main_window.load_instr_button.setEnabled(True)

    def load_selected_instruments(self):
        """Load selected instruments from station, then classify and update Lock-in/SMU config groups."""
        if not self.station:
            return False

        success_count = 0
        for item in self.main_window.instr_list.selectedItems():
            name = item.text()
            try:
                self.main_window.statusBar().showMessage(f"Loading {name}...")
                QApplication.processEvents()
                self.station.load_instrument(name)
                success_count += 1
            except Exception as e:
                print(f"Error loading {name}: {e}")
                self.main_window.statusBar().showMessage(f"Error loading {name}: {e}", 5000)

        self.main_window.statusBar().showMessage(f"Loaded {success_count} instruments.", 3000)

        if success_count > 0:
            lockin_names, smu_channel_list = classify_loaded_instruments(self.station)
            self.main_window.instruments_tab.populate_lockin_smu_config(lockin_names, smu_channel_list)

        return success_count > 0

    def populate_master_lockin_dropdown(self):
        """Populate the master lock-in dropdown with available instruments (if setup_tab exists)."""
        if not self.station:
            return
        setup_tab = getattr(self.main_window, 'setup_tab', None)
        if setup_tab is None:
            return
        combo = getattr(setup_tab.main_window, 'master_lockin_combo', None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        try:
            components = self.station.components
            instrument_names = sorted(components.keys())
            combo.addItems(instrument_names)
        except Exception as e:
            print(f"Error populating master lock-in dropdown: {e}")
        combo.blockSignals(False)
