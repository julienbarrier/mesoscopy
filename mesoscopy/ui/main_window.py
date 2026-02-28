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

    def start_logging(self):
        """Start qcodes command history and logger using the logs folder."""
        log_path = self.logs_folder_display.text().strip()
        err_label = getattr(self, "logs_error_display", None)
        if not log_path:
            if err_label:
                err_label.setText("Select a logs folder first.")
            return
        if not __import__("os").path.isdir(log_path):
            if err_label:
                err_label.setText("Logs path is not a directory.")
            return
        try:
            from qcodes.logger import start_command_history_logger, start_logger
            start_command_history_logger(log_path)
            start_logger()
            if err_label:
                err_label.setText("")
            self.statusBar().showMessage("Logging started.", 2000)
        except Exception as e:
            if err_label:
                err_label.setText(str(e))
            self.statusBar().showMessage(f"Logging error: {e}", 3000)

    def configure_lockins(self):
        """Apply lock-in configuration from the UI using configure_MFLI_osc_master, configure_sr_lockin, configure_MFLI."""
        err_label = getattr(self, "lockins_error_display", None)
        if not self.station:
            if err_label:
                err_label.setText("Load a station and instruments first.")
            return
        lockin_names = getattr(self, "lockin_name_fields", None) or []
        if not lockin_names:
            if err_label:
                err_label.setText("No lock-ins in configuration.")
            return
        try:
            from mesoscopy.instrument.lockin import (
                configure_MFLI_osc_master,
                configure_sr_lockin,
                configure_MFLI,
            )
            errors = []
            default_freq = 377.778
            default_tc = 0.03
            default_order = 4
            default_filter_slope = 24  # dB/oct for order 4
            master_done = False
            for idx, name_field in enumerate(lockin_names):
                name = name_field.text().strip()
                if not name or name not in self.station.components:
                    continue
                lockin = self.station.components[name]
                class_name = lockin.__class__.__name__
                role = "master"
                if getattr(self, "lockin_role_combos", None) and idx < len(self.lockin_role_combos):
                    role = self.lockin_role_combos[idx].currentText()
                is_mfli = "MFLI" in class_name or "HF2LI" in class_name
                is_sr = "SR830" in class_name or "SR860" in class_name or "SR865" in class_name
                try:
                    if is_mfli:
                        if role == "master":
                            configure_MFLI_osc_master(lockin, osc_idx=0, frequency=default_freq)
                            master_done = True
                        configure_MFLI(
                            lockin,
                            demod_idx=0,
                            time_constant=default_tc,
                            order=default_order,
                            V_drive=None,
                            adcselect=0 if role != "master" else None,
                        )
                    elif is_sr:
                        configure_sr_lockin(
                            lockin,
                            time_constant=default_tc,
                            filter_slope=default_filter_slope,
                        )
                except Exception as e:
                    errors.append(f"{name}: {e}")
            if errors:
                if err_label:
                    err_label.setText("\n".join(errors))
            else:
                if err_label:
                    err_label.setText("")
                self.statusBar().showMessage("Lock-ins configured.", 2000)
        except Exception as e:
            if err_label:
                err_label.setText(str(e))
            self.statusBar().showMessage(f"Configure lock-ins error: {e}", 3000)

    def configure_smu(self):
        """Apply SMU configuration from the UI using configure_smu_2614B_gate."""
        err_label = getattr(self, "smu_error_display", None)
        if not self.station:
            if err_label:
                err_label.setText("Load a station and instruments first.")
            return
        smu_inputs = getattr(self, "smu_inputs", None) or []
        if not smu_inputs:
            if err_label:
                err_label.setText("No SMU channels in configuration.")
            return
        current_range_map = {
            "100nA": 1e-7, "1µA": 1e-6, "10µA": 1e-5, "100µA": 1e-4,
            "1mA": 1e-3, "10mA": 1e-2, "100mA": 0.1, "1A": 1.0,
        }
        voltage_range_map = {
            "20mV": 0.02, "200mV": 0.2, "2V": 2.0, "20V": 20.0, "200V": 200.0,
        }
        try:
            from mesoscopy.instrument.smu import configure_smu_2614B_gate
            errors = []
            for idx in range(len(smu_inputs)):
                display_name = self.smu_inputs[idx].text().strip()
                if "." in display_name:
                    inst_name, ch = display_name.split(".", 1)
                    ch = ch.strip().lower()
                else:
                    inst_name = display_name
                    ch = None
                if inst_name not in self.station.components:
                    errors.append(f"{display_name}: instrument not in station")
                    continue
                inst = self.station.components[inst_name]
                if ch in ("smua", "smub"):
                    smu_ch = getattr(inst, ch, None)
                else:
                    smu_ch = inst
                if smu_ch is None:
                    errors.append(f"{display_name}: channel not found")
                    continue
                mode = self.smu_mode_inputs[idx].currentText()
                limiti = self.smu_limit_current_inputs[idx].value()
                limitv = self.smu_limit_voltage_inputs[idx].value()
                cr_text = self.smu_current_range_inputs[idx].currentText()
                vr_text = self.smu_voltage_range_inputs[idx].currentText()
                measurerange_i = current_range_map.get(cr_text, 1e-7)
                measurerange_v = voltage_range_map.get(vr_text, 20.0)
                nplc = self.smu_nplc_inputs[idx].value()
                output = self.smu_outputs_enabled_inputs[idx].isChecked()
                try:
                    configure_smu_2614B_gate(
                        smu_ch,
                        mode=mode,
                        limiti=limiti,
                        limitv=limitv,
                        measurerange_i=measurerange_i,
                        measurerange_v=measurerange_v,
                        sourcerange_v=measurerange_v,
                        nplc=nplc,
                        output=output,
                    )
                except Exception as e:
                    errors.append(f"{display_name}: {e}")
            if errors:
                if err_label:
                    err_label.setText("\n".join(errors))
            else:
                if err_label:
                    err_label.setText("")
                self.statusBar().showMessage("SMU configured.", 2000)
        except Exception as e:
            if err_label:
                err_label.setText(str(e))
            self.statusBar().showMessage(f"Configure SMU error: {e}", 3000)

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

