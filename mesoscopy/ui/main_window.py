"""Main window UI component."""
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QStatusBar
)
from PyQt6.QtCore import QThreadPool

from mesoscopy.core.constants import DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT, CONTENT_MARGINS
from mesoscopy.ui.tabs.instruments_tab import InstrumentsTab
from mesoscopy.ui.tabs.measurement_tab import MeasurementTab
from mesoscopy.ui.tabs.experiment_1d_tab import Experiment1DTab
from mesoscopy.ui.tabs.experiment_2d_tab import Experiment2DTab
from mesoscopy.ui.tabs.parameters_tab import ParametersTab
from mesoscopy.ui.dialogs import FileDialogs
from mesoscopy.ui.station_manager import StationManager
from mesoscopy.experiment.manager import ExperimentManager


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("mesoscoPy - Experiment Runner")
        self.setStatusBar(QStatusBar(self))

        self.station = None
        self.threadpool = QThreadPool()
        print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())

        self.tabs = QTabWidget()

        self.instruments_tab_widget = QWidget()
        self.measurement_tab_widget = QWidget()
        self.experiment_1d_widget = QWidget()
        self.experiment_2d_widget = QWidget()
        self.sweep_nD_tab = QWidget()
        self.parameters_tab = QWidget()

        self.tabs.addTab(self.instruments_tab_widget, "Instruments")
        self.tabs.addTab(self.measurement_tab_widget, "Measurement")
        self.tabs.addTab(self.experiment_1d_widget, "Sweep 1D")
        self.tabs.addTab(self.experiment_2d_widget, "Sweep 2D")
        self.tabs.addTab(self.sweep_nD_tab, "Sweep nD")
        self.tabs.addTab(self.parameters_tab, "Parameters")

        # Create wrapper widget with margins
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout()
        wrapper_layout.setContentsMargins(CONTENT_MARGINS, CONTENT_MARGINS, CONTENT_MARGINS, CONTENT_MARGINS)
        wrapper_layout.addWidget(self.tabs)
        wrapper.setLayout(wrapper_layout)

        self.setCentralWidget(wrapper)

        # Initialize managers and dialogs
        self.file_dialogs = FileDialogs(self)
        self.station_manager = StationManager(self)
        self.experiment_manager = ExperimentManager(self)

        # Initialize tabs
        self.instruments_tab = InstrumentsTab(self.instruments_tab_widget, self)
        self.measurement_tab = MeasurementTab(self.measurement_tab_widget, self)
        self.experiment_1d_tab = Experiment1DTab(self.experiment_1d_widget, self)
        self.experiment_2d_tab = Experiment2DTab(self.experiment_2d_widget, self)
        self.parameters_tab = ParametersTab(self.parameters_tab, self)

        # Update parameter forms after tab creation
        self.experiment_1d_tab.update_parameters_form()
        self.experiment_2d_tab.update_parameters_form()

    # Folder selection methods
    def select_db_folder(self):
        """Select database folder."""
        self.file_dialogs.select_db_folder()

    def select_station_folder(self):
        """Select station folder."""
        self.file_dialogs.select_station_folder()
    
    def select_logs_folder(self):
        """Select logs folder."""
        self.file_dialogs.select_logs_folder()

    # Station management methods
    def populate_station_files(self):
        """Populate the station file dropdown with .station.yaml files from the selected folder."""
        self.station_manager.populate_station_files()

    def load_station(self):
        """Load station from YAML configuration file."""
        self.station_manager.load_station()

    def populate_instrument_list(self, config_file=None):
        """Populate instrument list from station or YAML config file."""
        self.station_manager.populate_instrument_list(config_file)

    def load_selected_instruments(self):
        """Load selected instruments from station."""
        self.station_manager.load_selected_instruments()
    
    def populate_db_files(self):
        """Populate the database file dropdown with .db files from the selected folder."""
        folder = self.db_folder_display.text()
        if not folder or not __import__('os').path.isdir(folder):
            return
        
        self.db_file_combo.blockSignals(True)
        self.db_file_combo.clear()
        
        # Find all .db files in the folder
        import os
        db_files = [f for f in os.listdir(folder) if f.endswith('.db')]
        db_files.sort()
        
        if db_files:
            self.db_file_combo.addItems(db_files)
        
        # Add "New database" option at the end
        self.db_file_combo.addItem("New database")
        self.db_file_combo.blockSignals(False)

    # Experiment execution methods
    def run_experiment(self):
        """Run 1D experiment (Test Gates)."""
        self.experiment_manager.run_experiment_1d()

    def run_experiment_2d(self):
        """Run 2D experiment (Gate-Gate Mapping)."""
        self.experiment_manager.run_experiment_2d()

