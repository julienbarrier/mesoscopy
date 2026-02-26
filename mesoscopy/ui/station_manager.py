"""Station and instrument management."""
import os
import yaml
import qcodes
from qcodes.logger import start_command_history_logger, start_logger
from PyQt6.QtWidgets import QApplication, QListWidgetItem


class StationManager:
    """Manages station loading and instrument discovery."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.station = None

    def populate_station_files(self):
        """Populate the station file dropdown with .station.yaml files from the selected folder."""
        self.main_window.station_file_combo.clear()

        folder = self.main_window.station_folder_display.text()
        if not folder or not os.path.isdir(folder):
            return

        # Find all .station.yaml files in the folder
        station_files = [f for f in os.listdir(folder) if f.endswith('.station.yaml')]
        station_files.sort()

        if station_files:
            self.main_window.station_file_combo.addItems(station_files)
            # If only one file, it's automatically selected
            if len(station_files) == 1:
                self.main_window.station_file_combo.setCurrentIndex(0)

    def get_instruments_from_yaml(self, config_file):
        """Extract all instrument names from the 'instruments:' section of the station YAML file."""
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)

            if config and 'instruments' in config:
                return list(config['instruments'].keys())
            return []
        except Exception as e:
            print(f"Error reading instruments from YAML: {e}")
            return []

    def load_station(self):
        """Load station from YAML configuration file."""
        try:
            config_file = self.main_window.station_file_combo.currentText()
            if not config_file:
                self.main_window.statusBar().showMessage("Please select a station file.", 2000)
                return False

            # If a folder is selected, prepend it to the config file path
            folder = self.main_window.station_folder_display.text()
            if folder:
                config_file = os.path.join(folder, config_file)

            start_command_history_logger('../logs/')
            start_logger()
            self.station = qcodes.Station(config_file=config_file)
            self.main_window.station = self.station
            self.main_window.statusBar().showMessage("Station loaded successfully.", 2000)
            self.populate_instrument_list(config_file)
            # Populate instruments in the parameters tab
            self.main_window.parameters_tab.populate_instruments()
            # Populate master lock-in dropdown
            self.populate_master_lockin_dropdown()
            return True
        except Exception as e:
            self.main_window.statusBar().showMessage(f"Error loading station: {e}")
            return False

    def populate_instrument_list(self, config_file=None):
        """Populate instrument list from station or YAML config file."""
        # Clear existing items
        self.main_window.instr_list.clear()

        instr_names = []

        # Get instruments from the YAML file if config_file is provided
        if config_file:
            instr_names = self.get_instruments_from_yaml(config_file)
        elif self.station:
            # Fallback: try to get instruments from station config
            if hasattr(self.station, 'config') and self.station.config:
                if hasattr(self.station.config, 'instrument_configs'):
                    instr_names = list(self.station.config.instrument_configs.keys())
                elif hasattr(self.station.config, 'instruments'):
                    instr_names = list(self.station.config.instruments.keys())

        # Add items to list widget (all selected by default)
        for name in sorted(instr_names):
            item = QListWidgetItem(name)
            item.setSelected(True)
            self.main_window.instr_list.addItem(item)

        if instr_names:
            self.main_window.load_instr_button.setEnabled(True)

    def load_selected_instruments(self):
        """Load selected instruments from station."""
        if not self.station:
            return False

        success_count = 0
        # Get selected items from the list widget
        for item in self.main_window.instr_list.selectedItems():
            name = item.text()
            try:
                self.main_window.statusBar().showMessage(f"Loading {name}...")
                # Process events to show status message
                QApplication.processEvents()
                self.station.load_instrument(name)
                success_count += 1
            except Exception as e:
                print(f"Error loading {name}: {e}")
                self.main_window.statusBar().showMessage(f"Error loading {name}: {e}", 5000)

        self.main_window.statusBar().showMessage(f"Loaded {success_count} instruments.", 3000)
        return success_count > 0
    
    def populate_master_lockin_dropdown(self):
        """Populate the master lock-in dropdown with available instruments."""
        if not self.station:
            return
        
        self.main_window.setup_tab.main_window.master_lockin_combo.blockSignals(True)
        self.main_window.setup_tab.main_window.master_lockin_combo.clear()
        
        try:
            # Get all components from the station
            components = self.station.components
            instrument_names = sorted(components.keys())
            self.main_window.setup_tab.main_window.master_lockin_combo.addItems(instrument_names)
        except Exception as e:
            print(f"Error populating master lock-in dropdown: {e}")
        
        self.main_window.setup_tab.main_window.master_lockin_combo.blockSignals(False)
        return success_count > 0
