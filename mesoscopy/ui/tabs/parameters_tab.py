"""Parameters tab UI component."""
from PyQt6.QtWidgets import (
    QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QSizePolicy, QListWidget, QListWidgetItem,
    QComboBox, QLabel, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold


class ParametersTab:
    """Parameters tab for getting and setting instrument parameters"""
    
    def __init__(self, tab_widget, main_window):
        self.tab = tab_widget
        self.main_window = main_window
        self.get_parameter_rows = []  # List to store GET parameter row's widgets
        self.set_parameter_rows = []  # List to store SET parameter row's widgets
        self.get_group = None
        self.get_controls_container = None
        self.get_controls_layout = None
        self.set_controls_container = None
        self.set_controls_layout = None
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the parameters tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)
        
        # Set Parameters group with scroll area
        set_group = QGroupBox("Set")
        set_groupbox_title_bold(set_group)
        set_layout = QVBoxLayout()
        
        # Create scroll area for SET parameter rows
        set_scroll_area = QScrollArea()
        set_scroll_area.setWidgetResizable(True)
        self.set_controls_container = QWidget()
        self.set_controls_layout = QVBoxLayout()
        self.set_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.set_controls_layout.setSpacing(4)  # Reduce spacing between rows
        self.set_controls_container.setLayout(self.set_controls_layout)
        set_scroll_area.setWidget(self.set_controls_container)
        
        set_layout.addWidget(set_scroll_area)
        
        # Add SET parameter button
        add_set_param_button = QPushButton("Add parameter")
        add_set_param_button.clicked.connect(self.add_set_parameter_row)
        set_layout.addWidget(add_set_param_button)
        
        set_group.setLayout(set_layout)
        
        # Get Parameters group with scroll area
        self.get_group = QGroupBox("Get")
        set_groupbox_title_bold(self.get_group)
        get_layout = QVBoxLayout()
        
        # Create scroll area for GET parameter rows
        get_scroll_area = QScrollArea()
        get_scroll_area.setWidgetResizable(True)
        self.get_controls_container = QWidget()
        self.get_controls_layout = QVBoxLayout()
        self.get_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.get_controls_layout.setSpacing(4)  # Reduce spacing between rows
        self.get_controls_container.setLayout(self.get_controls_layout)
        get_scroll_area.setWidget(self.get_controls_container)
        
        get_layout.addWidget(get_scroll_area)
        
        # Add GET parameter button
        add_get_param_button = QPushButton("Add parameter")
        add_get_param_button.clicked.connect(self.add_get_parameter_row)
        get_layout.addWidget(add_get_param_button)
        
        self.get_group.setLayout(get_layout)
        
        main_layout.addWidget(set_group)
        main_layout.addWidget(self.get_group)
        
        # Add first GET parameter row
        self.add_get_parameter_row()
        # Add first SET parameter row
        self.add_set_parameter_row()
    
    def add_get_parameter_row(self):
        """Add a new GET parameter row dynamically."""
        row_index = len(self.get_parameter_rows)
        
        # Create row layout
        row_layout = QHBoxLayout()
        
        # Instrument selection dropdown
        instrument_combo = QComboBox()
        instrument_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        instrument_combo.addItem("Instrument:")  # Placeholder/label as first item
        instrument_combo.currentIndexChanged.connect(
            lambda idx: self.on_get_instrument_selected(row_index)
        )
        row_layout.addWidget(instrument_combo)
        
        # Parameter selection dropdown
        parameter_combo = QComboBox()
        parameter_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        parameter_combo.addItem("Parameter:")  # Placeholder/label as first item
        parameter_combo.currentIndexChanged.connect(
            lambda idx: self.on_get_parameter_selected(row_index)
        )
        row_layout.addWidget(parameter_combo)
        
        # Value display (read-only)
        value_display = QLineEdit()
        value_display.setReadOnly(True)
        value_display.setPlaceholderText("Value")
        row_layout.addWidget(value_display)
        
        # Update button
        update_button = QPushButton("↺")
        update_button.setMaximumWidth(40)
        update_button.clicked.connect(
            lambda: self.update_get_parameter_value(row_index)
        )
        row_layout.addWidget(update_button)
        
        # Remove button
        remove_button = QPushButton("✕")
        remove_button.setMaximumWidth(40)
        remove_button.clicked.connect(
            lambda: self.remove_get_parameter_row(row_index)
        )
        row_layout.addWidget(remove_button)
        
        # Store row widgets
        row_data = {
            'layout': row_layout,
            'instrument_combo': instrument_combo,
            'parameter_combo': parameter_combo,
            'value_display': value_display,
            'update_button': update_button,
            'remove_button': remove_button,
            'current_instrument': None,
            'current_parameters': {}
        }
        self.get_parameter_rows.append(row_data)
        
        # Add to controls layout
        self.get_controls_layout.addLayout(row_layout)
        
        # Populate instruments for this row
        self.populate_get_instruments_for_row(row_index)
    
    def remove_get_parameter_row(self, row_index):
        """Remove a GET parameter row."""
        if len(self.get_parameter_rows) <= 1:
            return  # Keep at least one row
        
        row_data = self.get_parameter_rows[row_index]
        
        # Remove all widgets from the layout
        layout = row_data['layout']
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Remove the layout from controls_layout
        self.get_controls_layout.removeItem(layout)
        
        # Remove from get_parameter_rows list
        self.get_parameter_rows.pop(row_index)
    
    def populate_instruments(self):
        """Populate the instrument dropdown for all rows from station.components."""
        self.populate_get_instruments()
        self.populate_set_instruments()
    
    def populate_get_instruments(self):
        """Populate the instrument dropdown for all GET rows from station.components."""
        for row_index in range(len(self.get_parameter_rows)):
            self.populate_get_instruments_for_row(row_index)
    
    def populate_get_instruments_for_row(self, row_index):
        """Populate the instrument dropdown for a specific GET row."""
        row_data = self.get_parameter_rows[row_index]
        combo = row_data['instrument_combo']
        
        combo.blockSignals(True)
        # Keep the first item (placeholder) and remove the rest
        while combo.count() > 1:
            combo.removeItem(1)
        
        if self.main_window.station:
            try:
                # Get all components from the station
                components = self.main_window.station.components
                instrument_names = sorted(components.keys())
                combo.addItems(instrument_names)
            except Exception as e:
                print(f"Error populating instruments: {e}")
        
        combo.blockSignals(False)
    
    def on_get_instrument_selected(self, row_index):
        """Handle instrument selection change for a specific GET row."""
        row_data = self.get_parameter_rows[row_index]
        instrument_name = row_data['instrument_combo'].currentText()
        
        # Check if placeholder is selected
        if not self.main_window.station or not instrument_name or instrument_name == "Instrument:":
            row_data['parameter_combo'].blockSignals(True)
            # Keep only the placeholder in parameter combo
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['parameter_combo'].blockSignals(False)
            row_data['current_parameters'] = {}
            row_data['value_display'].clear()
            return
        
        try:
            # Get the instrument object
            instrument = self.main_window.station.components[instrument_name]
            row_data['current_instrument'] = instrument
            
            # Get all parameters from the instrument
            row_data['parameter_combo'].blockSignals(True)
            # Keep only the placeholder and remove the rest
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['current_parameters'] = {}
            
            # Get all parameters (attributes that have a .get method)
            for attr_name in dir(instrument):
                if not attr_name.startswith('_'):
                    try:
                        attr = getattr(instrument, attr_name)
                        # Check if it's a parameter or has a get method
                        if hasattr(attr, 'get') and callable(attr.get):
                            row_data['current_parameters'][attr_name] = attr
                    except:
                        pass
            
            # Add parameters to dropdown
            param_names = sorted(row_data['current_parameters'].keys())
            row_data['parameter_combo'].addItems(param_names)
            row_data['parameter_combo'].blockSignals(False)
            
            # Clear value display
            row_data['value_display'].clear()
        except Exception as e:
            print(f"Error selecting instrument: {e}")
            row_data['parameter_combo'].blockSignals(True)
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['parameter_combo'].blockSignals(False)
            row_data['current_parameters'] = {}
            row_data['value_display'].clear()
    
    def on_get_parameter_selected(self, row_index):
        """Handle parameter selection change for a specific GET row."""
        row_data = self.get_parameter_rows[row_index]
        # Clear the value display when parameter changes
        row_data['value_display'].clear()
    
    def update_get_parameter_value(self, row_index):
        """Update the displayed parameter value by calling .get() for a specific GET row."""
        row_data = self.get_parameter_rows[row_index]
        parameter_name = row_data['parameter_combo'].currentText()
        
        if not parameter_name or parameter_name not in row_data['current_parameters']:
            row_data['value_display'].clear()
            return
        
        try:
            parameter = row_data['current_parameters'][parameter_name]
            # Call the .get() method to retrieve the current value
            value = parameter.get()
            
            # Format the value for display based on type
            if isinstance(value, (int, float)):
                # For numeric values, include unit if available (from qcodes)
                unit = getattr(parameter, 'unit', '')
                if unit:
                    value_str = f"{value:.6g} {unit}"
                else:
                    value_str = f"{value:.6g}"
            else:
                # For string values, display naturally without quotes
                value_str = str(value)
            
            row_data['value_display'].setText(value_str)
        except Exception as e:
            row_data['value_display'].setText(f"Error: {e}")
            print(f"Error updating parameter value: {e}")
    
    # SET Parameter Methods
    
    def add_set_parameter_row(self):
        """Add a new SET parameter row dynamically."""
        row_index = len(self.set_parameter_rows)
        
        # Create row layout
        row_layout = QHBoxLayout()
        
        # Instrument selection dropdown
        instrument_combo = QComboBox()
        instrument_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        instrument_combo.addItem("Instrument:")  # Placeholder/label as first item
        instrument_combo.currentIndexChanged.connect(
            lambda idx: self.on_set_instrument_selected(row_index)
        )
        row_layout.addWidget(instrument_combo)
        
        # Parameter selection dropdown (only settable parameters)
        parameter_combo = QComboBox()
        parameter_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        parameter_combo.addItem("Parameter:")  # Placeholder/label as first item
        parameter_combo.currentIndexChanged.connect(
            lambda idx: self.on_set_parameter_selected(row_index)
        )
        row_layout.addWidget(parameter_combo)
        
        # Value input field (editable)
        value_input = QLineEdit()
        value_input.setPlaceholderText("Value")
        row_layout.addWidget(value_input)
        
        # Set button
        set_button = QPushButton("Set")
        set_button.setMaximumWidth(50)
        set_button.clicked.connect(
            lambda: self.set_parameter_value(row_index)
        )
        row_layout.addWidget(set_button)
        
        # Remove button
        remove_button = QPushButton("✕")
        remove_button.setMaximumWidth(40)
        remove_button.clicked.connect(
            lambda: self.remove_set_parameter_row(row_index)
        )
        row_layout.addWidget(remove_button)
        
        # Store row widgets
        row_data = {
            'layout': row_layout,
            'instrument_combo': instrument_combo,
            'parameter_combo': parameter_combo,
            'value_input': value_input,
            'set_button': set_button,
            'remove_button': remove_button,
            'current_instrument': None,
            'current_parameters': {}
        }
        self.set_parameter_rows.append(row_data)
        
        # Add to controls layout
        self.set_controls_layout.addLayout(row_layout)
        
        # Populate instruments for this row
        self.populate_set_instruments_for_row(row_index)
    
    def remove_set_parameter_row(self, row_index):
        """Remove a SET parameter row."""
        if len(self.set_parameter_rows) <= 1:
            return  # Keep at least one row
        
        row_data = self.set_parameter_rows[row_index]
        
        # Remove all widgets from the layout
        layout = row_data['layout']
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Remove the layout from controls_layout
        self.set_controls_layout.removeItem(layout)
        
        # Remove from set_parameter_rows list
        self.set_parameter_rows.pop(row_index)
    
    def populate_set_instruments(self):
        """Populate the instrument dropdown for all SET rows from station.components."""
        for row_index in range(len(self.set_parameter_rows)):
            self.populate_set_instruments_for_row(row_index)
    
    def populate_set_instruments_for_row(self, row_index):
        """Populate the instrument dropdown for a specific SET row."""
        row_data = self.set_parameter_rows[row_index]
        combo = row_data['instrument_combo']
        
        combo.blockSignals(True)
        # Keep the first item (placeholder) and remove the rest
        while combo.count() > 1:
            combo.removeItem(1)
        
        if self.main_window.station:
            try:
                # Get all components from the station
                components = self.main_window.station.components
                instrument_names = sorted(components.keys())
                combo.addItems(instrument_names)
            except Exception as e:
                print(f"Error populating instruments: {e}")
        
        combo.blockSignals(False)
    
    def on_set_instrument_selected(self, row_index):
        """Handle instrument selection change for a specific SET row."""
        row_data = self.set_parameter_rows[row_index]
        instrument_name = row_data['instrument_combo'].currentText()
        
        # Check if placeholder is selected
        if not self.main_window.station or not instrument_name or instrument_name == "Instrument:":
            row_data['parameter_combo'].blockSignals(True)
            # Keep only the placeholder in parameter combo
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['parameter_combo'].blockSignals(False)
            row_data['current_parameters'] = {}
            row_data['value_input'].clear()
            row_data['value_input'].setPlaceholderText("Value")
            return
        
        try:
            # Get the instrument object
            instrument = self.main_window.station.components[instrument_name]
            row_data['current_instrument'] = instrument
            
            # Get all parameters with set_cmd from the instrument
            row_data['parameter_combo'].blockSignals(True)
            # Keep only the placeholder and remove the rest
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['current_parameters'] = {}
            
            # Get all parameters (attributes that have a .set method)
            for attr_name in dir(instrument):
                if not attr_name.startswith('_'):
                    try:
                        attr = getattr(instrument, attr_name)
                        # Check if it's a parameter with set_cmd
                        if hasattr(attr, 'set_cmd') and attr.set_cmd is not None:
                            row_data['current_parameters'][attr_name] = attr
                    except:
                        pass
            
            # Add parameters to dropdown
            param_names = sorted(row_data['current_parameters'].keys())
            row_data['parameter_combo'].addItems(param_names)
            row_data['parameter_combo'].blockSignals(False)
            
            # Clear value input and reset placeholder
            row_data['value_input'].clear()
            row_data['value_input'].setPlaceholderText("Value")
        except Exception as e:
            print(f"Error selecting instrument: {e}")
            row_data['parameter_combo'].blockSignals(True)
            while row_data['parameter_combo'].count() > 1:
                row_data['parameter_combo'].removeItem(1)
            row_data['parameter_combo'].blockSignals(False)
            row_data['current_parameters'] = {}
            row_data['value_input'].clear()
    
    def on_set_parameter_selected(self, row_index):
        """Handle parameter selection change for a specific SET row."""
        row_data = self.set_parameter_rows[row_index]
        parameter_name = row_data['parameter_combo'].currentText()
        
        # Check if placeholder is selected
        if not parameter_name or parameter_name == "Parameter:":
            row_data['value_input'].clear()
            row_data['value_input'].setPlaceholderText("Value")
            return
        
        # Update placeholder with unit
        if parameter_name in row_data['current_parameters']:
            parameter = row_data['current_parameters'][parameter_name]
            unit = getattr(parameter, 'unit', '')
            if unit:
                row_data['value_input'].setPlaceholderText(f"Value ({unit})")
            else:
                row_data['value_input'].setPlaceholderText("Value")
        
        row_data['value_input'].clear()
    
    def set_parameter_value(self, row_index):
        """Set the parameter value by calling .set() for a specific SET row."""
        row_data = self.set_parameter_rows[row_index]
        parameter_name = row_data['parameter_combo'].currentText()
        value_str = row_data['value_input'].text()
        
        if not parameter_name or parameter_name == "Parameter:" or not value_str:
            return
        
        if parameter_name not in row_data['current_parameters']:
            return
        
        try:
            parameter = row_data['current_parameters'][parameter_name]
            # Convert value to appropriate type based on parameter
            param_type = type(parameter.get())
            
            if isinstance(param_type(), (int, float)):
                value = float(value_str)
            else:
                value = value_str
            
            # Call the .set() method to set the value
            parameter.set(value)
            
            # Show success message
            row_data['value_input'].setStyleSheet("background-color: #90EE90;")
            self.main_window.statusBar().showMessage(f"Set {parameter_name} to {value}", 2000)
            
            # Reset color after a moment
            row_data['value_input'].setStyleSheet("")
        except Exception as e:
            row_data['value_input'].setStyleSheet("background-color: #FFB6C6;")
            self.main_window.statusBar().showMessage(f"Error setting {parameter_name}: {e}", 3000)
            print(f"Error setting parameter value: {e}")