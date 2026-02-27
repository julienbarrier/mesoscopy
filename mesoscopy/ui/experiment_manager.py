"""Experiment execution and management."""
from mesoscopy.core.worker import Worker
from mesoscopy.plotting import LivePlottingSubscriber
from mesoscopy.experiments import TestGatesExperiment, GateGateMappingExperiment


class ExperimentManager:
    """Manages experiment execution."""

    def __init__(self, main_window):
        self.main_window = main_window

    def run_experiment_1d(self):
        """Run 1D experiment (Test Gates)."""
        if not self.main_window.station:
            self.main_window.statusBar().showMessage("Please load a station first.", 2000)
            return

        experiment_class = TestGatesExperiment

        try:
            kwargs = self.main_window.experiment_1d_tab.get_parameters()
        except ValueError as e:
            self.main_window.statusBar().showMessage(f"Invalid parameter value: {e}", 2000)
            return

        db_file = self.main_window.db_file_input.text()
        exp_name_str = self.main_window.exp_name_input.text()
        sample_name = self.main_window.sample_name_input.text()

        n_points = kwargs.get('n_points', 101)
        subscriber = LivePlottingSubscriber(self.main_window.experiment_1d_tab.plot_canvas, n_points, 1)

        worker = Worker(
            self._run_experiment_task, 
            experiment_class, 
            db_file, 
            exp_name_str, 
            sample_name, 
            kwargs, 
            [subscriber]
        )
        worker.signals.finished.connect(self._experiment_finished_1d)
        worker.signals.error.connect(self._experiment_error_1d)

        self.main_window.threadpool.start(worker)
        self.main_window.experiment_1d_tab.run_button.setEnabled(False)

    def run_experiment_2d(self):
        """Run 2D experiment (Gate-Gate Mapping)."""
        if not self.main_window.station:
            self.main_window.statusBar().showMessage("Please load a station first.", 2000)
            return

        experiment_class = GateGateMappingExperiment

        try:
            kwargs = self.main_window.experiment_2d_tab.get_parameters()
        except ValueError as e:
            self.main_window.statusBar().showMessage(f"Invalid parameter value: {e}", 2000)
            return

        db_file = self.main_window.db_file_input.text()
        exp_name_str = self.main_window.exp_name_input.text()
        sample_name = self.main_window.sample_name_input.text()

        n_points = kwargs.get('n_points', 101)
        subscriber = LivePlottingSubscriber(
            self.main_window.experiment_2d_tab.plot_canvas, 
            n_points, 
            n_points
        )

        worker = Worker(
            self._run_experiment_task, 
            experiment_class, 
            db_file, 
            exp_name_str, 
            sample_name, 
            kwargs, 
            [subscriber]
        )
        worker.signals.finished.connect(self._experiment_finished_2d)
        worker.signals.error.connect(self._experiment_error_2d)

        self.main_window.threadpool.start(worker)
        self.main_window.experiment_2d_tab.run_button.setEnabled(False)

    def _experiment_finished_1d(self):
        """Called when 1D experiment finishes."""
        self.main_window.statusBar().showMessage("Experiment finished.", 2000)
        self.main_window.experiment_1d_tab.run_button.setEnabled(True)

    def _experiment_finished_2d(self):
        """Called when 2D experiment finishes."""
        self.main_window.statusBar().showMessage("Experiment finished.", 2000)
        self.main_window.experiment_2d_tab.run_button.setEnabled(True)

    def _experiment_error_1d(self, err):
        """Handle 1D experiment error."""
        self.main_window.statusBar().showMessage(f"Experiment error: {err[1]}", 5000)
        self.main_window.experiment_1d_tab.run_button.setEnabled(True)

    def _experiment_error_2d(self, err):
        """Handle 2D experiment error."""
        self.main_window.statusBar().showMessage(f"Experiment error: {err[1]}", 5000)
        self.main_window.experiment_2d_tab.run_button.setEnabled(True)

    def _run_experiment_task(self, experiment_class, db_file, exp_name, sample_name, kwargs, subscribers):
        """Execute experiment in separate thread."""
        print(f"Running {exp_name} with parameters: {kwargs}")
        experiment_instance = experiment_class(self.main_window.station, db_file, exp_name, sample_name)
        experiment_instance.run(subscribers=subscribers, **kwargs)
