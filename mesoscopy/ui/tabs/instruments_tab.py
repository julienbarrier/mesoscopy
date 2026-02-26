"""Instruments tab UI components."""
from PyQt6.QtWidgets import (
    QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QSizePolicy, QListWidget,
    QComboBox, QLabel, QWidget, QDoubleSpinBox, QCheckBox, QGridLayout,
)
from ui.tabs.ui_helpers import set_groupbox_title_bold


class InstrumentsTab:
    """Instruments tab for station and instrument configuration."""

    def __init__(self, tab_widget, main_window):
        self.tab = tab_widget
        self.main_window = main_window
        self.slave_lockin_combos = {}
        self.setup_ui()

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

        self.main_window.station_folder_display = QLineEdit()
        self.main_window.station_folder_display.setReadOnly(True)
        self.main_window.station_folder_display.setPlaceholderText("Station folder")
        self.main_window.station_folder_button = QPushButton("Browse...")
        self.main_window.station_folder_button.clicked.connect(self.main_window.select_station_folder)

        station_folder_layout = QHBoxLayout()
        station_folder_layout.addWidget(self.main_window.station_folder_display)
        station_folder_layout.addWidget(self.main_window.station_folder_button)

        self.main_window.station_file_combo = QComboBox()
        self.main_window.station_file_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.main_window.station_file_combo.setPlaceholderText("Station file")

        station_fields_layout = QVBoxLayout()
        station_fields_layout.setSpacing(0)
        station_fields_layout.addLayout(station_folder_layout)
        station_fields_layout.addWidget(self.main_window.station_file_combo)

        station_layout.addRow(station_fields_layout)

        self.main_window.load_station_button = QPushButton("Load Station")
        self.main_window.load_station_button.clicked.connect(self.main_window.load_station)
        station_layout.addRow(self.main_window.load_station_button)

        instruments_left.addWidget(station_group)

        # Instruments group
        instr_group = QGroupBox("Instruments to Load")
        set_groupbox_title_bold(instr_group)
        instr_layout = QVBoxLayout()

        self.main_window.instr_list = QListWidget()
        self.main_window.instr_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        instr_layout.addWidget(self.main_window.instr_list)

        self.main_window.load_instr_button = QPushButton("Load Selected Instruments")
        self.main_window.load_instr_button.setEnabled(False)
        self.main_window.load_instr_button.clicked.connect(self.main_window.load_selected_instruments)
        instr_layout.addWidget(self.main_window.load_instr_button)

        instr_group.setLayout(instr_layout)
        instr_group.setMinimumHeight(500)
        instruments_left.addWidget(instr_group)

        # Logs group
        logs_group = QGroupBox("Logs")
        set_groupbox_title_bold(logs_group)
        logs_layout = QFormLayout()
        logs_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        logs_group.setLayout(logs_layout)

        self.main_window.logs_folder_display = QLineEdit()
        self.main_window.logs_folder_display.setReadOnly(True)
        self.main_window.logs_folder_button = QPushButton("Browse...")
        self.main_window.logs_folder_button.clicked.connect(self.main_window.select_logs_folder)

        logs_folder_layout = QHBoxLayout()
        logs_folder_layout.addWidget(self.main_window.logs_folder_display)
        logs_folder_layout.addWidget(self.main_window.logs_folder_button)

        logs_layout.addRow("Logs folder:", logs_folder_layout)

        instruments_left.addWidget(logs_group)
        instruments_left.addStretch()

        # Right side - Lock-ins, SMU
        instruments_right = QVBoxLayout()

        # Lock-ins Configuration group
        lockins_group = QGroupBox("Lock-ins Configuration")
        set_groupbox_title_bold(lockins_group)
        lockins_layout = QVBoxLayout()

        # Grid of lock-in name fields (2 rows x 6 columns)
        lockins_grid = QGridLayout()
        self.main_window.lockin_name_fields = []
        self.main_window.lockin_type_combos = []
        self.main_window.lockin_role_combos = []
        self.main_window.lockin_extref_combos = []
        self.main_window.lockin_oscillator_combos = []
        
        for row in range(2):
            for col in range(6):
                # Create a container widget for each grid cell
                cell_widget = QWidget()
                cell_layout = QVBoxLayout()
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.setSpacing(2)
                
                # Lock-in name field
                lockin_field = QLineEdit()
                lockin_field.setReadOnly(True)
                lockin_field.setText("Lock-in name")
                self.main_window.lockin_name_fields.append(lockin_field)
                cell_layout.addWidget(lockin_field)
                
                # Measurement type dropdown
                type_combo = QComboBox()
                type_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                type_combo.addItems(['Vdiff', 'V+', 'I', 'AuxIn1', 'AuxIn2'])
                self.main_window.lockin_type_combos.append(type_combo)
                cell_layout.addWidget(type_combo)
                
                # Master/Slave dropdown
                role_combo = QComboBox()
                role_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                role_combo.addItems(['master', 'slave'])
                # First item defaults to master, all others default to slave
                idx = row * 6 + col
                if idx == 0:
                    role_combo.setCurrentIndex(0)  # master
                else:
                    role_combo.setCurrentIndex(1)  # slave
                self.main_window.lockin_role_combos.append(role_combo)
                cell_layout.addWidget(role_combo)
                
                # ExtRef dropdown (only for slave lock-ins)
                extref_combo = QComboBox()
                extref_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                extref_combo.addItems(['Sig In1', 'Curr In 1', 'Trigger 1', 'Trigger 2', 'Aux In 1', 'Aux In 2'])
                # Show for slaves (all except first), hide for master (first)
                extref_combo.setCurrentIndex(2)  # Default to Trigger 1
                extref_combo.setVisible(idx != 0)
                self.main_window.lockin_extref_combos.append(extref_combo)
                cell_layout.addWidget(extref_combo)
                
                # Oscillator output dropdown (only for master lock-ins)
                oscillator_combo = QComboBox()
                oscillator_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                oscillator_combo.addItems(['Trigger Out 1', 'Trigger Out 2'])
                # Show for master (first), hide for slaves (all others)
                oscillator_combo.setVisible(idx == 0)
                self.main_window.lockin_oscillator_combos.append(oscillator_combo)
                cell_layout.addWidget(oscillator_combo)
                
                # Connect role change to show/hide ExtRef/Oscillator combos
                role_combo.currentIndexChanged.connect(
                    lambda checked, index=idx: self.on_lockin_role_changed(index)
                )
                
                cell_widget.setLayout(cell_layout)
                lockins_grid.addWidget(cell_widget, row, col)
        
        lockins_layout.addLayout(lockins_grid)

        # Add configure button
        self.main_window.configure_lockins_button = QPushButton("Configure Lock-ins")
        lockins_layout.addWidget(self.main_window.configure_lockins_button)

        lockins_group.setLayout(lockins_layout)
        instruments_right.addWidget(lockins_group)

        # SMU Configuration group
        smu_group = QGroupBox("SMU Configuration")
        set_groupbox_title_bold(smu_group)
        smu_layout = QGridLayout()

        # Create 3 sets of SMU fields
        self.main_window.smu_inputs = []
        self.main_window.smu_mode_inputs = []
        self.main_window.smu_limit_current_inputs = []
        self.main_window.smu_limit_voltage_inputs = []
        self.main_window.smu_current_range_inputs = []
        self.main_window.smu_voltage_range_inputs = []
        self.main_window.smu_nplc_inputs = []
        self.main_window.smu_outputs_enabled_inputs = []

        for i in range(3):
            # SMU field
            smu_input = QLineEdit()
            smu_input.setReadOnly(True)
            self.main_window.smu_inputs.append(smu_input)
            
            # Mode dropdown
            mode_input = QComboBox()
            mode_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            mode_input.addItems(['voltage', 'current'])
            self.main_window.smu_mode_inputs.append(mode_input)
            
            # Limit current spinbox
            limit_current = QDoubleSpinBox()
            limit_current.setRange(1e-8, 1e-3)
            limit_current.setDecimals(9)
            limit_current.setSingleStep(1e-8)
            self.main_window.smu_limit_current_inputs.append(limit_current)
            
            # Limit voltage spinbox
            limit_voltage = QDoubleSpinBox()
            limit_voltage.setRange(1e-6, 200)
            limit_voltage.setDecimals(6)
            limit_voltage.setSingleStep(0.1)
            self.main_window.smu_limit_voltage_inputs.append(limit_voltage)
            
            # Current range dropdown
            current_range = QComboBox()
            current_range.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            current_range.addItems(['100nA', '1µA', '10µA', '100µA', '1mA', '10mA', '100mA', '1A'])
            self.main_window.smu_current_range_inputs.append(current_range)
            
            # Voltage range dropdown
            voltage_range = QComboBox()
            voltage_range.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            voltage_range.addItems(['20mV', '200mV', '2V', '20V', '200V'])
            voltage_range.setCurrentIndex(3)  # Default to 20V
            self.main_window.smu_voltage_range_inputs.append(voltage_range)
            
            # NPLC spinbox
            nplc = QDoubleSpinBox()
            nplc.setRange(0.01, 10.0)
            nplc.setDecimals(2)
            nplc.setSingleStep(0.01)
            nplc.setValue(1.00)
            self.main_window.smu_nplc_inputs.append(nplc)
            
            # Outputs enabled checkbox
            outputs_enabled = QCheckBox()
            self.main_window.smu_outputs_enabled_inputs.append(outputs_enabled)

        # Add labels and widgets to grid
        row = 0
        smu_layout.addWidget(QLabel("Instrument/Channel"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Mode"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_mode_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Limit current (A)"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_limit_current_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Limit voltage (V)"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_limit_voltage_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Current range (A)"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_current_range_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Voltage range (V)"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_voltage_range_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("NPLC"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_nplc_inputs[i], row, i + 1)
        
        row += 1
        smu_layout.addWidget(QLabel("Outputs enabled"), row, 0)
        for i in range(3):
            smu_layout.addWidget(self.main_window.smu_outputs_enabled_inputs[i], row, i + 1)

        # Add configure button
        row += 1
        self.main_window.configure_smu_button = QPushButton("Configure Source-Measure-Units")
        smu_layout.addWidget(self.main_window.configure_smu_button, row, 0, 1, 4)

        smu_group.setLayout(smu_layout)
        instruments_right.addWidget(smu_group)
        instruments_right.addStretch()

        main_layout.addWidget(instruments_left_widget)
        main_layout.addLayout(instruments_right)

    def on_lockin_role_changed(self, index):
        """Handle master/slave role change for lock-in amplifiers."""
        role_combo = self.main_window.lockin_role_combos[index]
        extref_combo = self.main_window.lockin_extref_combos[index]
        oscillator_combo = self.main_window.lockin_oscillator_combos[index]
        
        # Show ExtRef combo if 'slave' is selected, hide otherwise
        # Show oscillator combo if 'master' is selected, hide otherwise
        if role_combo.currentText() == 'slave':
            extref_combo.setVisible(True)
            oscillator_combo.setVisible(False)
        else:
            extref_combo.setVisible(False)
            oscillator_combo.setVisible(True)

    def on_master_lockin_changed(self):
        """Handle master lock-in selection change and populate oscillator output parameters and slave lock-ins."""
        master_lockin_name = self.main_window.master_lockin_combo.currentText()

        # Update oscillator output dropdown
        self.main_window.oscillator_output_combo.blockSignals(True)
        self.main_window.oscillator_output_combo.clear()

        # Update slave lock-ins
        self.populate_slave_lockins(master_lockin_name)

        if not self.main_window.station or not master_lockin_name:
            self.main_window.oscillator_output_combo.blockSignals(False)
            return

        try:
            # Get the master lock-in instrument
            instrument = self.main_window.station.components.get(master_lockin_name)
            if not instrument:
                self.main_window.oscillator_output_combo.blockSignals(False)
                return

            # Get all oscillator parameters (oscs, oscs[index].freq, etc.)
            osc_parameters = []
            for attr_name in dir(instrument):
                if not attr_name.startswith('_'):
                    try:
                        attr = getattr(instrument, attr_name)
                        # Look for oscillator related attributes
                        if 'osc' in attr_name.lower() or 'freq' in attr_name.lower():
                            if hasattr(attr, '__len__'):
                                # Handle indexed oscillators like oscs[0], oscs[1], etc.
                                try:
                                    for idx in range(len(attr)):
                                        osc_parameters.append(f"{attr_name}[{idx}]")
                                except Exception:
                                    osc_parameters.append(attr_name)
                            else:
                                osc_parameters.append(attr_name)
                    except Exception:
                        pass

            # Add oscillator parameters to dropdown
            osc_parameters.sort()
            self.main_window.oscillator_output_combo.addItems(osc_parameters)
        except Exception as e:
            print(f"Error populating oscillator output parameters: {e}")

        self.main_window.oscillator_output_combo.blockSignals(False)

    def populate_slave_lockins(self, master_lockin_name):
        """Populate slave lock-in dropdowns based on master lock-in selection."""
        # Clear existing slave lock-in rows
        while self.slave_lockins_layout.rowCount() > 0:
            self.slave_lockins_layout.removeRow(0)
        self.slave_lockin_combos.clear()

        if not self.main_window.station or not master_lockin_name:
            return

        try:
            # Get all instruments
            components = self.main_window.station.components
            slave_lockin_types = ('SR830', 'SR860', 'SR865', 'MFLI', 'HF2LI')

            # Find all slave lock-ins (exclude master lock-in)
            slave_lockins = []
            for name, instrument in components.items():
                if name != master_lockin_name:
                    instrument_class = instrument.__class__.__name__
                    if any(ltype in instrument_class for ltype in slave_lockin_types):
                        slave_lockins.append((name, instrument))

            # Create rows for each slave lock-in
            for slave_name, slave_instrument in sorted(slave_lockins):
                # Create dropdown for slave lock-in parameters
                slave_combo = QComboBox()
                slave_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

                # Get all parameters (oscillator/demod related) from slave lock-in
                slave_parameters = []
                for attr_name in dir(slave_instrument):
                    if not attr_name.startswith('_'):
                        try:
                            attr = getattr(slave_instrument, attr_name)
                            # Look for oscillator, demod, or measurement related attributes
                            if any(keyword in attr_name.lower() for keyword in ['osc', 'demod', 'freq', 'sample']):
                                if hasattr(attr, '__len__'):
                                    # Handle indexed attributes like demods[0], demods[1], etc.
                                    try:
                                        for idx in range(len(attr)):
                                            slave_parameters.append(f"{attr_name}[{idx}]")
                                    except Exception:
                                        slave_parameters.append(attr_name)
                                else:
                                    slave_parameters.append(attr_name)
                        except Exception:
                            pass

                # Add parameters to dropdown
                slave_parameters.sort()
                slave_combo.addItems(slave_parameters)

                # Store the combo box with the slave lock-in name as key
                self.slave_lockin_combos[slave_name] = slave_combo

                # Add row to the layout
                self.slave_lockins_layout.addRow(slave_name, slave_combo)

        except Exception as e:
            print(f"Error populating slave lock-ins: {e}")
