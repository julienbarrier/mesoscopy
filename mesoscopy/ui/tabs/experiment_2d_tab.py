"""2D Experiment (Gate-Gate Mapping) tab UI component."""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFormLayout
)
from mesoscopy.experiment.experiments import GateGateMappingExperiment
from mesoscopy.core.plotting import MplCanvas
from mesoscopy.ui.tabs.ui_helpers import update_parameter_form, get_parameters_from_widgets


class Experiment2DTab:
    """2D Experiment tab (Gate-Gate Mapping)."""

    def __init__(self, tab_widget, main_window):
        self.tab = tab_widget
        self.main_window = main_window
        self.param_widgets = []
        self.setup_ui()

    def setup_ui(self):
        """Initialize the 2D experiment tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        controls_layout = QVBoxLayout()
        main_layout.addLayout(controls_layout)

        # Label for experiment type
        exp_label = QLabel("Experiment: Gate-Gate Mapping")
        controls_layout.addWidget(exp_label)

        self.exp_experiment = GateGateMappingExperiment

        self.param_form = QFormLayout()
        controls_layout.addLayout(self.param_form)

        buttons_layout = QHBoxLayout()
        controls_layout.addLayout(buttons_layout)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.main_window.run_experiment_2d)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")

        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.pause_button)
        buttons_layout.addWidget(self.stop_button)

        self.plot_canvas = MplCanvas(self.main_window, width=5, height=4, dpi=100)
        main_layout.addWidget(self.plot_canvas)

    def update_parameters_form(self):
        """Update parameters form for Sweep 2D (Gate-Gate Mapping)."""
        experiment_class = GateGateMappingExperiment
        self.param_widgets = update_parameter_form(experiment_class, self.param_form)

    def get_parameters(self):
        """Extract parameter values from widgets."""
        experiment_class = GateGateMappingExperiment
        return get_parameters_from_widgets(experiment_class, self.param_widgets)
