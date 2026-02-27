"""Measurement tab UI components."""
from PyQt6.QtWidgets import (
    QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QSizePolicy, QComboBox,
)
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold


class MeasurementTab:
    """Measurement tab for database and measurement configuration."""

    def __init__(self, tab_widget, main_window):
        self.tab = tab_widget
        self.main_window = main_window
        self.setup_ui()

    def setup_ui(self):
        """Set up the measurement tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        # Left side - Database and Experiment Info
        measurement_left = QVBoxLayout()

        # Database and Experiment Info group
        db_group = QGroupBox("Database and Experiment Info")
        set_groupbox_title_bold(db_group)
        db_layout = QFormLayout()
        db_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        db_group.setLayout(db_layout)

        self.main_window.db_folder_display = QLineEdit()
        self.main_window.db_folder_display.setReadOnly(True)
        self.main_window.db_folder_button = QPushButton("Browse...")
        self.main_window.db_folder_button.clicked.connect(self.main_window.select_db_folder)

        db_folder_layout = QHBoxLayout()
        db_folder_layout.addWidget(self.main_window.db_folder_display)
        db_folder_layout.addWidget(self.main_window.db_folder_button)

        self.main_window.db_file_combo = QComboBox()
        self.main_window.db_file_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.main_window.db_file_combo.currentIndexChanged.connect(self.on_db_file_changed)

        self.main_window.new_db_name_input = QLineEdit()
        self.main_window.new_db_name_input.setPlaceholderText("Enter new database name")
        self.main_window.new_db_name_input.setVisible(False)

        self.main_window.exp_name_input = QLineEdit("Toberemoved")
        self.main_window.sample_name_input = QLineEdit("")

        db_layout.addRow("Database folder:", db_folder_layout)
        db_layout.addRow("Database file:", self.main_window.db_file_combo)
        db_layout.addRow("", self.main_window.new_db_name_input)
        db_layout.addRow("Experiment name:", self.main_window.exp_name_input)
        db_layout.addRow("Sample name:", self.main_window.sample_name_input)

        measurement_left.addWidget(db_group)
        measurement_left.addStretch()

        # Right side - Measurement and Gate Configuration
        measurement_right = QVBoxLayout()

        # Measurement Configuration group
        measurement_group = QGroupBox("Measurement Configuration")
        set_groupbox_title_bold(measurement_group)
        measurement_layout = QFormLayout()
        measurement_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.main_window.frequency_input = QLineEdit()
        self.main_window.time_constant_input = QLineEdit()
        self.main_window.filter_order_input = QLineEdit()
        self.main_window.vout_amplitude_input = QLineEdit()
        self.main_window.line_resistance_input = QLineEdit()
        self.main_window.voltage_divider_input = QLineEdit()

        measurement_layout.addRow("Frequency (Hz)", self.main_window.frequency_input)
        measurement_layout.addRow("Time constant (s)", self.main_window.time_constant_input)
        measurement_layout.addRow("Filter order", self.main_window.filter_order_input)
        measurement_layout.addRow("Vout amplitude (V)", self.main_window.vout_amplitude_input)
        measurement_layout.addRow("Line resistance (Ohm) - then auto display current Iout", self.main_window.line_resistance_input)
        measurement_layout.addRow("Voltage divider ratio - then auto display voltage at sample Vsample", self.main_window.voltage_divider_input)

        measurement_group.setLayout(measurement_layout)
        measurement_right.addWidget(measurement_group)

        # Gate Configuration group
        gate_group = QGroupBox("Gate Configuration")
        set_groupbox_title_bold(gate_group)
        gate_layout = QFormLayout()
        gate_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.main_window.top_gate_voltage_input = QLineEdit()
        self.main_window.top_gate_leakage_input = QLineEdit()
        self.main_window.top_gate_max_value_input = QLineEdit()
        self.main_window.top_gate_max_rate_input = QLineEdit()
        self.main_window.back_gate_voltage_input = QLineEdit()
        self.main_window.back_gate_leakage_input = QLineEdit()
        self.main_window.back_gate_max_value_input = QLineEdit()
        self.main_window.back_gate_max_rate_input = QLineEdit()
        self.main_window.breakout_current_input = QLineEdit()

        gate_layout.addRow("Top_gate_voltage", self.main_window.top_gate_voltage_input)
        gate_layout.addRow("Top_gate_leakage", self.main_window.top_gate_leakage_input)
        gate_layout.addRow("Top_gate_max_value (V)", self.main_window.top_gate_max_value_input)
        gate_layout.addRow("Top_gate_max_rate (V/s)", self.main_window.top_gate_max_rate_input)
        gate_layout.addRow("Back_gate_voltage", self.main_window.back_gate_voltage_input)
        gate_layout.addRow("Back_gate_leakage", self.main_window.back_gate_leakage_input)
        gate_layout.addRow("Back_gate_max_value (V)", self.main_window.back_gate_max_value_input)
        gate_layout.addRow("Back_gate_max_rate (V/s)", self.main_window.back_gate_max_rate_input)
        gate_layout.addRow("Breakout current (pA)", self.main_window.breakout_current_input)

        gate_group.setLayout(gate_layout)
        measurement_right.addWidget(gate_group)
        measurement_right.addStretch()

        main_layout.addLayout(measurement_left)
        main_layout.addLayout(measurement_right)

    def on_db_file_changed(self):
        """Handle database file selection change."""
        selected_file = self.main_window.db_file_combo.currentText()

        if selected_file == "New database":
            # Show the new database name input
            self.main_window.new_db_name_input.setVisible(True)
            self.main_window.new_db_name_input.clear()
            self.main_window.new_db_name_input.setFocus()
        else:
            # Hide the new database name input
            self.main_window.new_db_name_input.setVisible(False)
