"""1D Experiment (Test Gates) tab UI component."""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit, QSpinBox, QCheckBox, QScrollArea, QGroupBox
)
from mesoscopy.experiments import TestGatesExperiment
from mesoscopy.plotting import MplCanvas
from mesoscopy.ui.tabs.ui_helpers import (
    add_labeled_row,
    update_parameter_form,
    get_parameters_from_widgets,
    set_groupbox_title_bold,
)


class Experiment1DTab:
    """1D Experiment tab (Test Gates)."""

    def __init__(self, tab_widget, main_window):
        self.tab = tab_widget
        self.main_window = main_window
        self.param_widgets = []
        self.experiment_name_input = None
        self.measurement_name_input = None
        self.sweep_class_combo = None
        self.instrument_combo = None
        self.parameter_combo = None
        self.start_input = None
        self.stop_input = None
        self.num_points_input = None
        self.delay_input = None
        self.together_instrument1_combo = None
        self.together_parameter1_combo = None
        self.together_start1_input = None
        self.together_stop1_input = None
        self.together_instrument2_combo = None
        self.together_parameter2_combo = None
        self.together_start2_input = None
        self.together_stop2_input = None
        self.breakout_checkbox = None
        self.measured_params_rows = []
        self.measured_params_container = None
        self.measured_params_layout = None
        self.sweep_row1_layout = None
        self.sweep_row1_container = None
        self.sweep_row2_layout = None
        self.together_row1_layout = None
        self.together_row2_layout = None
        self.together_row1_container = None
        self.together_row2_container = None
        self.setup_ui()

    def setup_ui(self):
        """Initialize the 1D experiment tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(4)
        main_layout.addLayout(controls_layout)

        # Experiment Name row
        self.experiment_name_input = QLineEdit()
        self.experiment_name_input.setText("Test Gates")
        self.experiment_name_input.setPlaceholderText("Enter experiment name")
        add_labeled_row(controls_layout, "Experiment Name:", self.experiment_name_input)

        self.exp_experiment = TestGatesExperiment

        # Sweep class selection row
        self.sweep_class_combo = QComboBox()
        self.sweep_class_combo.addItems(["LinSweep", "LogSweep", "ArraySweep", "TogetherSweep"])
        self.sweep_class_combo.setCurrentText("LinSweep")
        self.sweep_class_combo.currentIndexChanged.connect(self.on_sweep_class_changed)
        add_labeled_row(controls_layout, "Sweep class:", self.sweep_class_combo)

        # Sweep options (instrument, parameter, delay) - shown conditionally
        # Row 1: Instrument and Parameter
        sweep_row1_layout = QHBoxLayout()
        
        instrument_label = QLabel("Instrument:")
        self.instrument_combo = QComboBox()
        self.instrument_combo.setPlaceholderText("Instrument")
        self.instrument_combo.currentIndexChanged.connect(self.on_instrument_changed)
        sweep_row1_layout.addWidget(instrument_label)
        sweep_row1_layout.addWidget(self.instrument_combo)
        
        parameter_label = QLabel("Parameter:")
        self.parameter_combo = QComboBox()
        self.parameter_combo.setPlaceholderText("Parameter")
        sweep_row1_layout.addWidget(parameter_label)
        sweep_row1_layout.addWidget(self.parameter_combo)
        
        sweep_row1_layout.addStretch()
        sweep_row1_container = QWidget()
        sweep_row1_container.setLayout(sweep_row1_layout)
        controls_layout.addWidget(sweep_row1_container)
        
        # TogetherSweep rows (two instruments/parameters with start/stop)
        together_row1_layout = QHBoxLayout()

        together_instr1_label = QLabel("Sweep 1:")
        self.together_instrument1_combo = QComboBox()
        self.together_instrument1_combo.setPlaceholderText("Instrument")
        together_row1_layout.addWidget(together_instr1_label)
        together_row1_layout.addWidget(self.together_instrument1_combo)

        self.together_parameter1_combo = QComboBox()
        self.together_parameter1_combo.setPlaceholderText("Parameter")
        together_row1_layout.addWidget(self.together_parameter1_combo)

        together_start1_label = QLabel("Start1:")
        self.together_start1_input = QLineEdit()
        self.together_start1_input.setText("0.0")
        self.together_start1_input.setPlaceholderText("Start value")
        together_row1_layout.addWidget(together_start1_label)
        together_row1_layout.addWidget(self.together_start1_input)

        together_stop1_label = QLabel("Stop1:")
        self.together_stop1_input = QLineEdit()
        self.together_stop1_input.setText("1.0")
        self.together_stop1_input.setPlaceholderText("Stop value")
        together_row1_layout.addWidget(together_stop1_label)
        together_row1_layout.addWidget(self.together_stop1_input)

        together_row1_layout.addStretch()
        together_row1_container = QWidget()
        together_row1_container.setLayout(together_row1_layout)
        controls_layout.addWidget(together_row1_container)

        together_row2_layout = QHBoxLayout()

        together_instr2_label = QLabel("Sweep 2:")
        self.together_instrument2_combo = QComboBox()
        self.together_instrument2_combo.setPlaceholderText("Instrument")
        together_row2_layout.addWidget(together_instr2_label)
        together_row2_layout.addWidget(self.together_instrument2_combo)

        self.together_parameter2_combo = QComboBox()
        self.together_parameter2_combo.setPlaceholderText("Parameter")
        together_row2_layout.addWidget(self.together_parameter2_combo)

        together_start2_label = QLabel("Start2:")
        self.together_start2_input = QLineEdit()
        self.together_start2_input.setText("0.0")
        self.together_start2_input.setPlaceholderText("Start value")
        together_row2_layout.addWidget(together_start2_label)
        together_row2_layout.addWidget(self.together_start2_input)

        together_stop2_label = QLabel("Stop2:")
        self.together_stop2_input = QLineEdit()
        self.together_stop2_input.setText("1.0")
        self.together_stop2_input.setPlaceholderText("Stop value")
        together_row2_layout.addWidget(together_stop2_label)
        together_row2_layout.addWidget(self.together_stop2_input)

        together_row2_layout.addStretch()
        together_row2_container = QWidget()
        together_row2_container.setLayout(together_row2_layout)
        controls_layout.addWidget(together_row2_container)

        # Row 2: Start, Stop, Num points, Delay
        sweep_row2_layout = QHBoxLayout()

        start_label = QLabel("Start:")
        self.start_input = QLineEdit()
        self.start_input.setText("0.0")
        self.start_input.setPlaceholderText("Start value")
        sweep_row2_layout.addWidget(start_label)
        sweep_row2_layout.addWidget(self.start_input)

        stop_label = QLabel("Stop:")
        self.stop_input = QLineEdit()
        self.stop_input.setText("1.0")
        self.stop_input.setPlaceholderText("Stop value")
        sweep_row2_layout.addWidget(stop_label)
        sweep_row2_layout.addWidget(self.stop_input)

        num_points_label = QLabel("Num points:")
        self.num_points_input = QSpinBox()
        self.num_points_input.setMinimum(1)
        self.num_points_input.setMaximum(999999)
        self.num_points_input.setValue(101)
        sweep_row2_layout.addWidget(num_points_label)
        sweep_row2_layout.addWidget(self.num_points_input)

        delay_label = QLabel("Delay (s):")
        self.delay_input = QLineEdit()
        self.delay_input.setText("0.6")
        self.delay_input.setPlaceholderText("Delay in seconds")
        sweep_row2_layout.addWidget(delay_label)
        sweep_row2_layout.addWidget(self.delay_input)

        sweep_row2_layout.addStretch()
        controls_layout.addLayout(sweep_row2_layout)
        
        # Measured Parameters block
        measured_params_group = QGroupBox("Measured Parameters")
        set_groupbox_title_bold(measured_params_group)
        measured_params_group_layout = QVBoxLayout()
        measured_params_group_layout.setSpacing(4)
        
        # Scroll area for measured parameters
        measured_params_scroll = QScrollArea()
        measured_params_scroll.setWidgetResizable(True)
        self.measured_params_container = QWidget()
        self.measured_params_layout = QVBoxLayout()
        self.measured_params_layout.setContentsMargins(0, 0, 0, 0)
        self.measured_params_layout.setSpacing(4)
        self.measured_params_container.setLayout(self.measured_params_layout)
        measured_params_scroll.setWidget(self.measured_params_container)
        
        measured_params_group_layout.addWidget(measured_params_scroll)
        
        # Add button for measured parameters
        add_measured_param_button = QPushButton("Add parameter")
        add_measured_param_button.clicked.connect(self.add_measured_parameter_row)
        measured_params_group_layout.addWidget(add_measured_param_button)
        
        measured_params_group.setLayout(measured_params_group_layout)
        measured_params_group.setMinimumHeight(150)
        controls_layout.addWidget(measured_params_group)
        
        # Measurement name row
        self.measurement_name_input = QLineEdit()
        self.measurement_name_input.setText("")
        self.measurement_name_input.setPlaceholderText("Enter measurement name")
        add_labeled_row(controls_layout, "Measurement name:", self.measurement_name_input)
        
        # Breakout on gate leakage checkbox
        breakout_layout = QHBoxLayout()
        self.breakout_checkbox = QCheckBox("Breakout on gate leakage")
        self.breakout_checkbox.setChecked(False)
        breakout_layout.addWidget(self.breakout_checkbox)
        breakout_layout.addStretch()
        controls_layout.addLayout(breakout_layout)
        
        # Store references to layout items for visibility control
        self.sweep_row1_layout = sweep_row1_layout
        self.sweep_row1_container = sweep_row1_container
        self.sweep_row2_layout = sweep_row2_layout
        self.together_row1_layout = together_row1_layout
        self.together_row2_layout = together_row2_layout
        self.together_row1_container = together_row1_container
        self.together_row2_container = together_row2_container
        self.sweep_options_layout = None  # No longer needed as single layout
        
        # Initialize sweep options visibility
        self.set_together_rows_visible(False)
        self.on_sweep_class_changed()

        # Wire TogetherSweep instrument changes
        self.together_instrument1_combo.currentIndexChanged.connect(
            lambda: self.on_measured_instrument_changed(self.together_instrument1_combo, self.together_parameter1_combo)
        )
        self.together_instrument2_combo.currentIndexChanged.connect(
            lambda: self.on_measured_instrument_changed(self.together_instrument2_combo, self.together_parameter2_combo)
        )

        self.param_form = QFormLayout()
        controls_layout.addLayout(self.param_form)

        buttons_layout = QHBoxLayout()
        controls_layout.addLayout(buttons_layout)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.main_window.run_experiment)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")

        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.pause_button)
        buttons_layout.addWidget(self.stop_button)

        self.plot_canvas = MplCanvas(self.main_window, width=5, height=4, dpi=100)
        main_layout.addWidget(self.plot_canvas)

    def update_parameters_form(self):
        """Update parameters form for Sweep 1D (Test Gates)."""
        experiment_class = TestGatesExperiment
        self.param_widgets = update_parameter_form(experiment_class, self.param_form)

    def get_parameters(self):
        """Extract parameter values from widgets."""
        experiment_class = TestGatesExperiment
        return get_parameters_from_widgets(experiment_class, self.param_widgets)
    
    def get_sweep_class(self):
        """Get the selected sweep class."""
        return self.sweep_class_combo.currentText()
    
    def on_sweep_class_changed(self):
        """Handle sweep class selection change."""
        sweep_class = self.sweep_class_combo.currentText()
        
        # Row visibility for sweep options
        show_row1 = sweep_class in ["LinSweep", "LogSweep", "ArraySweep"]
        show_row2 = sweep_class in ["LinSweep", "LogSweep", "ArraySweep", "TogetherSweep"]
        show_together_rows = sweep_class == "TogetherSweep"
        self.set_sweep_row1_visible(show_row1)
        self.set_sweep_row2_visible(show_row2)
        self.set_together_rows_visible(show_together_rows)
        
        # Show start/stop fields only for LinSweep and LogSweep
        show_start_stop = sweep_class in ["LinSweep", "LogSweep"]
        self.set_start_stop_visible(show_start_stop)

        # Show num points for LinSweep/LogSweep/TogetherSweep; hide for ArraySweep
        show_num_points = sweep_class in ["LinSweep", "LogSweep", "TogetherSweep"]
        self.set_num_points_visible(show_num_points)
    
    def set_sweep_row1_visible(self, visible):
        """Show or hide sweep row 1 (instrument, parameter)."""
        if self.sweep_row1_container is not None:
            self.sweep_row1_container.setVisible(visible)
        for i in range(self.sweep_row1_layout.count()):
            widget = self.sweep_row1_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(visible)

    def set_sweep_row2_visible(self, visible):
        """Show or hide sweep row 2 (start, stop, num points, delay)."""
        for i in range(self.sweep_row2_layout.count()):
            widget = self.sweep_row2_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(visible)

    def set_together_rows_visible(self, visible):
        """Show or hide TogetherSweep rows."""
        if not self.together_row1_layout or not self.together_row2_layout:
            return
        if self.together_row1_container is not None:
            self.together_row1_container.setVisible(visible)
        if self.together_row2_container is not None:
            self.together_row2_container.setVisible(visible)
        for i in range(self.together_row1_layout.count()):
            widget = self.together_row1_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(visible)
        for i in range(self.together_row2_layout.count()):
            widget = self.together_row2_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(visible)
    
    def set_start_stop_visible(self, visible):
        """Show or hide start/stop fields."""
        # Find and toggle start/stop labels and inputs in row 2
        for i in range(self.sweep_row2_layout.count()):
            widget = self.sweep_row2_layout.itemAt(i).widget()
            if widget and isinstance(widget, QLabel):
                if widget.text() in ("Start:", "Stop:"):
                    widget.setVisible(visible)
            elif widget and isinstance(widget, QLineEdit):
                if widget == self.start_input or widget == self.stop_input:
                    widget.setVisible(visible)

    def set_num_points_visible(self, visible):
        """Show or hide num points field."""
        for i in range(self.sweep_row2_layout.count()):
            widget = self.sweep_row2_layout.itemAt(i).widget()
            if widget and isinstance(widget, QLabel):
                if widget.text() == "Num points:":
                    widget.setVisible(visible)
            elif widget and isinstance(widget, QSpinBox):
                if widget == self.num_points_input:
                    widget.setVisible(visible)
    
    def on_instrument_changed(self):
        """Handle instrument selection change and populate parameters."""
        if not self.main_window.station:
            self.parameter_combo.clear()
            return
        
        instrument_name = self.instrument_combo.currentText()
        if not instrument_name:
            self.parameter_combo.clear()
            return
        
        try:
            instrument = self.main_window.station.components.get(instrument_name)
            if not instrument:
                self.parameter_combo.clear()
                return
            
            # Get all parameters from the instrument
            parameters = []
            for attr_name in dir(instrument):
                if not attr_name.startswith('_'):
                    try:
                        attr = getattr(instrument, attr_name)
                        # Get parameter names (exclude methods and special attributes)
                        if hasattr(attr, 'get') and callable(attr.get):
                            parameters.append(attr_name)
                    except:
                        pass
            
            self.parameter_combo.blockSignals(True)
            self.parameter_combo.clear()
            self.parameter_combo.addItems(sorted(parameters))
            self.parameter_combo.blockSignals(False)
        except Exception as e:
            print(f"Error populating parameters: {e}")
            self.parameter_combo.clear()
    
    def populate_instruments(self):
        """Populate instrument dropdown from station."""
        if not self.main_window.station:
            self.instrument_combo.clear()
            if self.together_instrument1_combo:
                self.together_instrument1_combo.clear()
            if self.together_instrument2_combo:
                self.together_instrument2_combo.clear()
            return
        
        self.instrument_combo.blockSignals(True)
        self.instrument_combo.clear()
        
        # Add all instruments from station
        instruments = list(self.main_window.station.components.keys())
        self.instrument_combo.addItems(sorted(instruments))
        if self.together_instrument1_combo is not None:
            self.together_instrument1_combo.addItems(sorted(instruments))
        if self.together_instrument2_combo is not None:
            self.together_instrument2_combo.addItems(sorted(instruments))
        
        self.instrument_combo.blockSignals(False)
        self.on_instrument_changed()

        if self.together_instrument1_combo is not None:
            self.on_measured_instrument_changed(self.together_instrument1_combo, self.together_parameter1_combo)
        if self.together_instrument2_combo is not None:
            self.on_measured_instrument_changed(self.together_instrument2_combo, self.together_parameter2_combo)
    
    def add_measured_parameter_row(self):
        """Add a new measured parameter row."""
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        
        # Label field
        label_input = QLineEdit()
        label_input.setPlaceholderText("Parameter label")
        row_layout.addWidget(label_input)
        
        # Instrument dropdown
        instrument_combo = QComboBox()
        instrument_combo.setPlaceholderText("Instrument")
        if self.main_window.station:
            instruments = list(self.main_window.station.components.keys())
            instrument_combo.addItems(sorted(instruments))
        instrument_combo.currentIndexChanged.connect(lambda: self.on_measured_instrument_changed(instrument_combo, parameter_combo))
        row_layout.addWidget(instrument_combo)
        
        # Parameter dropdown
        parameter_combo = QComboBox()
        parameter_combo.setPlaceholderText("Parameter")
        row_layout.addWidget(parameter_combo)
        
        # Delete button
        delete_button = QPushButton("✕")
        delete_button.setMaximumWidth(30)
        delete_button.clicked.connect(lambda: self.remove_measured_parameter_row(row_layout))
        row_layout.addWidget(delete_button)
        
        # Store row reference
        self.measured_params_rows.append({
            'layout': row_layout,
            'label': label_input,
            'instrument': instrument_combo,
            'parameter': parameter_combo
        })
        
        # Add to container
        self.measured_params_layout.addLayout(row_layout)
    
    def on_measured_instrument_changed(self, instrument_combo, parameter_combo):
        """Handle instrument selection change for measured parameters."""
        if not self.main_window.station:
            parameter_combo.clear()
            return
        
        instrument_name = instrument_combo.currentText()
        if not instrument_name:
            parameter_combo.clear()
            return
        
        try:
            instrument = self.main_window.station.components.get(instrument_name)
            if not instrument:
                parameter_combo.clear()
                return
            
            # Get all parameters from the instrument
            parameters = []
            for attr_name in dir(instrument):
                if not attr_name.startswith('_'):
                    try:
                        attr = getattr(instrument, attr_name)
                        # Get parameter names (exclude methods and special attributes)
                        if hasattr(attr, 'get') and callable(attr.get):
                            parameters.append(attr_name)
                    except:
                        pass
            
            parameter_combo.blockSignals(True)
            parameter_combo.clear()
            parameter_combo.addItems(sorted(parameters))
            parameter_combo.blockSignals(False)
        except Exception as e:
            print(f"Error populating parameters: {e}")
            parameter_combo.clear()
    
    def remove_measured_parameter_row(self, row_layout):
        """Remove a measured parameter row."""
        # Find and remove the row from stored references
        for i, row in enumerate(self.measured_params_rows):
            if row['layout'] == row_layout:
                self.measured_params_rows.pop(i)
                break
        
        # Remove all widgets from layout
        while row_layout.count():
            item = row_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
