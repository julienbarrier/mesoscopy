"""Sweep tab: configure and run a dond measurement of 1 to 4 dimensions."""
import copy

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox, QScrollArea, QGroupBox,
    QProgressBar, QSpinBox, QLabel, QFrame, QMessageBox,
)
from mesoscopy.experiment.snake import make_snake
from mesoscopy.core import recipes
from mesoscopy.core.dry_run import check_request
from mesoscopy.core.dond_options import (
    build_namespace, build_options, check_run, default_advanced, describe_changes, make_callable, normalise_advanced,
)
from mesoscopy.core.run_progress import RunProgress, axis_positions, format_estimate
from mesoscopy.services.run_queue import IDLE as QUEUE_IDLE, RUNNING as RUNNING_ITEM
from mesoscopy.services.run_controller import IDLE, PAUSED, PAUSING, RUNNING, STOPPING, RunRequest, swept_parameters
from mesoscopy.ui.tabs.advanced_dialog import AdvancedDialog
from mesoscopy.ui.tabs.experiment_name_box import ExperimentNameBox
from mesoscopy.ui.tabs.measured_box import MeasuredParametersBox
from mesoscopy.ui.tabs.live_plot import LivePlotPanel
from mesoscopy.ui.tabs.sweep_box import SweepDimensionBox
from mesoscopy.ui.tabs.ui_helpers import add_labeled_row, set_groupbox_title_bold

MAX_DIMENSIONS = 4


class SweepTab(QObject):
    """Sweep tab. Each dimension is a SweepDimensionBox; they are passed to QCoDeS ``dond`` in
    the order shown: the first box is the outermost loop (slowest axis), the last box is the
    innermost loop (fastest axis). Dimensions are added and removed at the outer end."""

    def __init__(self, tab_widget, services):
        super().__init__()  # a QObject: it subscribes to the signals of the services
        self.tab = tab_widget
        self.services = services
        self.dimension_boxes = []
        self._running = False
        self._progress = None
        self._axis_sizes = []
        self._pending_state = None  # a restored setup whose parameters are not available yet
        self._run_state = IDLE
        self._queue_active = False  # the queue is waiting for or running recipes
        self._run_boxes = []        # the boxes of the measurement in progress (their progress bars)
        self._retired = []          # containers of boxes removed during a run, deleted when it ends
        self._run_ramp = False      # "Ramp to 0 when finished" for the measurement in progress
        self.advanced = default_advanced()  # the dond options of the advanced settings (the axes keep their own)
        self._editing = None        # the queue item whose recipe is being edited here
        self._pick_target = None    # (edit, text, selector, box) of the Start or Stop field a click on the plot fills in
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_axis_progress)
        self.setup_ui()
        # follow the services instead of being called: the experiment parameters, the settings and the run
        services.registry.parametersChanged.connect(self._on_parameters_changed)
        services.settings.changed.connect(self.update_breakout_availability)
        services.settings.changed.connect(self._apply_plot_memory)
        self._apply_plot_memory()
        run = services.run
        run.runStateChanged.connect(self._on_run_state)
        run.runStarted.connect(self._on_run_started)
        run.runFinished.connect(self._on_run_finished)
        run.runIdKnown.connect(self.plot_panel.set_run_id)
        run.runIdsKnown.connect(self.plot_panel.set_run_ids)
        run.liveRunStarted.connect(self.plot_panel.add_live_run)
        run.liveDataChanged.connect(self.plot_panel.live_data_changed)
        # the plot fills in the Start or Stop field the cursor is in (run-to-run feedback)
        self.plot_panel.valuePicked.connect(self._on_value_picked)
        self.plot_panel.rangePicked.connect(self._on_range_picked)
        self.plot_panel.runAnnotated.connect(services.data.runMetadataChanged)  # the Data tab's table follows
        self.plot_panel.limitRequested.connect(self._on_limit_requested)
        self.plot_panel.limit_provider = self._limit_info
        QApplication.instance().focusChanged.connect(self._focus_changed)
        queue = services.queue
        queue.stateChanged.connect(self._on_queue_state)
        queue.changed.connect(self._on_queue_changed)
        queue.addCurrentRequested.connect(self.add_to_queue)
        queue.replaceRequested.connect(self.replace_queue_item)
        queue.editRequested.connect(self.edit_queue_item)

    def setup_ui(self):
        """Initialize the Sweep tab UI.

        Layout: [ experiment name / [dimensions | measured parameters] / run controls ] [ plot ]
        """
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(4)
        main_layout.addLayout(controls_layout, 3)

        # shown while the recipe of a queue item is edited here
        self.edit_banner = QFrame()
        self.edit_banner.setStyleSheet("QFrame { background: #fff3cd; border-radius: 4px; } QLabel { color: #664d03; }")
        banner_layout = QHBoxLayout(self.edit_banner)
        self.edit_banner_label = QLabel("")
        banner_layout.addWidget(self.edit_banner_label, 1)
        update_item = QPushButton("Update item")
        update_item.clicked.connect(self.update_edited_item)
        cancel_edit = QPushButton("Cancel")
        cancel_edit.clicked.connect(self.end_editing)
        banner_layout.addWidget(update_item)
        banner_layout.addWidget(cancel_edit)
        self.edit_banner.setVisible(False)
        controls_layout.addWidget(self.edit_banner)

        self.run_hint = QLabel("A measurement is running and is not affected by changes here. Prepare the next one and "
                               "click \"Add to queue\".")
        self.run_hint.setWordWrap(True)
        self.run_hint.setStyleSheet("color: #1565c0;")
        self.run_hint.setVisible(False)
        controls_layout.addWidget(self.run_hint)

        # Experiment Name row
        self.experiment_name_input = ExperimentNameBox(self.services)  # a dropdown of the experiments of the folder
        add_labeled_row(controls_layout, "Experiment Name:", self.experiment_name_input)

        # Measurement name row: right after the experiment name, above the two boxes
        self.measurement_name_input = QLineEdit()
        self.measurement_name_input.setPlaceholderText("Enter measurement name")
        add_labeled_row(controls_layout, "Measurement name:", self.measurement_name_input)

        columns_layout = QHBoxLayout()
        controls_layout.addLayout(columns_layout, 1)

        # Column 1 - sweep dimensions (scrollable: up to MAX_DIMENSIONS boxes)
        dimensions_column = QVBoxLayout()
        columns_layout.addLayout(dimensions_column, 3)

        dimensions_scroll = QScrollArea()
        dimensions_scroll.setWidgetResizable(True)
        dimensions_scroll.setMinimumWidth(430)
        dimensions_container = QWidget()
        self.dimensions_layout = QVBoxLayout(dimensions_container)
        self.dimensions_layout.setContentsMargins(0, 0, 0, 0)
        self.dimensions_layout.setSpacing(4)
        # after all the axes boxes: the snake toggle (two axes only) and the repetitions
        self.options_widget = QWidget()
        options_layout = QVBoxLayout(self.options_widget)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(2)
        self.snake_checkbox = QCheckBox("Snake sweep")
        self.snake_checkbox.setToolTip(
            "Reverse the inner axis on every other pass of the outer axis, so that the inner axis goes back and "
            "forth without jumping to its start. The dataset holds the real values, in the order they were swept."
        )
        self.snake_checkbox.toggled.connect(lambda _: self.update_run_estimate())
        options_layout.addWidget(self.snake_checkbox)
        repeat_row = QHBoxLayout()
        self.repeat_checkbox = QCheckBox("Repeat")
        self.repeat_checkbox.setToolTip(
            "Run the whole measurement several times, one after the other. Each repetition is a run of its own "
            "in the database, named with its number."
        )
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 999)
        self.repeat_spin.setValue(2)
        self.repeat_spin.setEnabled(False)
        self.repeat_checkbox.toggled.connect(self.repeat_spin.setEnabled)
        self.repeat_checkbox.toggled.connect(lambda _: self.update_run_estimate())
        self.repeat_spin.valueChanged.connect(lambda _: self.update_run_estimate())
        repeat_row.addWidget(self.repeat_checkbox)
        repeat_row.addWidget(self.repeat_spin)
        repeat_row.addWidget(QLabel("times"))
        repeat_row.addStretch()
        options_layout.addLayout(repeat_row)
        self.back_forth_checkbox = QCheckBox("Sweep back and forth")
        self.back_forth_checkbox.setToolTip(
            "On every other repetition, sweep the axis from its last value to its first (the array is reversed, or the "
            "start and stop of a linear or log sweep are swapped). Needs a single axis and Repeat.")
        self.back_forth_checkbox.setEnabled(False)  # until Repeat is ticked
        self.repeat_checkbox.toggled.connect(self.back_forth_checkbox.setEnabled)
        self.back_forth_checkbox.toggled.connect(lambda _: self.update_run_estimate())
        options_layout.addWidget(self.back_forth_checkbox)
        self.no_axis_label = QLabel("No sweep axis: the measured parameters (traces, for instance) are acquired once.")
        self.no_axis_label.setWordWrap(True)
        self.no_axis_label.setStyleSheet("color: gray;")
        self.no_axis_label.setVisible(False)
        self.dimensions_layout.addWidget(self.no_axis_label)
        self.dimensions_layout.addWidget(self.options_widget)
        self.dimensions_layout.addStretch()
        dimensions_scroll.setWidget(dimensions_container)
        dimensions_column.addWidget(dimensions_scroll, 1)

        dimension_buttons = QHBoxLayout()
        self.add_dimension_button = QPushButton()
        self.add_dimension_button.setToolTip("Add a new outermost (slowest) axis")
        self.add_dimension_button.clicked.connect(self.add_dimension)
        self.remove_dimension_button = QPushButton("Remove dimension")
        self.remove_dimension_button.setToolTip("Remove the outermost (slowest) axis")
        self.remove_dimension_button.clicked.connect(self.remove_dimension)
        dimension_buttons.addWidget(self.add_dimension_button)
        dimension_buttons.addWidget(self.remove_dimension_button)
        dimensions_column.addLayout(dimension_buttons)

        # Column 2 - Measured Parameters block
        self.measured_box = MeasuredParametersBox(self.services)
        self.measured_params_group = self.measured_box  # locked while a measurement runs
        measured_params_group = self.measured_box
        columns_layout.addWidget(measured_params_group, 2)

        # Breakout on gate leakage checkbox
        breakout_layout = QHBoxLayout()
        self.breakout_checkbox = QCheckBox("Stop on breakout conditions")
        self.breakout_checkbox.setChecked(False)
        self.update_breakout_availability()
        breakout_layout.addWidget(self.breakout_checkbox)
        self.ramp_checkbox = QCheckBox("Ramp to 0 when finished")
        self.ramp_checkbox.setChecked(False)
        self.ramp_checkbox.clicked.connect(self._on_ramp_clicked)
        self.ramp_checkbox.setToolTip(
            "When the measurement ends (by itself, on a breakout condition or with Stop), bring every swept "
            "parameter to 0 at its maximum ramp rate. A parameter without a ramp rate is set directly."
        )
        breakout_layout.addWidget(self.ramp_checkbox)
        self.advanced_button = QPushButton("Advanced settings...")
        self.advanced_button.clicked.connect(self.open_advanced)
        breakout_layout.addWidget(self.advanced_button)
        breakout_layout.addStretch()
        controls_layout.addLayout(breakout_layout)

        buttons_layout = QHBoxLayout()
        controls_layout.addLayout(buttons_layout)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.request_run)
        self.run_button.setEnabled(False)  # until a measurement name is given
        self.measurement_name_input.textChanged.connect(lambda _: self._update_run_enabled())
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)  # only while a measurement runs
        self.pause_button.setToolTip("Pause after the current point, and resume. The instruments stay as they are.")
        self.pause_button.clicked.connect(self.services.run.toggle_pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)  # only while a measurement runs
        self.stop_button.clicked.connect(self.services.run.stop)
        self.stop_ramp_button = QPushButton("Stop and ramp to 0")
        self.stop_ramp_button.setEnabled(False)  # only while a measurement runs
        self.stop_ramp_button.setToolTip(
            "Stop after the current point, then bring every swept parameter to 0 at its maximum ramp rate "
            "(the Parameter explorer sets it; a parameter without one is set directly)."
        )
        self.stop_ramp_button.clicked.connect(self.services.run.stop_and_ramp_to_zero)
        self.check_button = QPushButton("Check setup")
        self.check_button.setToolTip(
            "Dry run: check the sweeps against the limits, ramp rates and alarms of the parameters, the free disk space "
            "and the time it will take, without touching an instrument. Errors also stop the Run button and the queue.")
        self.check_button.clicked.connect(self.check_setup)
        self.queue_button = QPushButton("Add to queue")
        self.queue_button.setToolTip("Add this setup as a recipe at the end of the queue (Queue tab).")
        self.queue_button.clicked.connect(self.add_to_queue)
        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.check_button)
        buttons_layout.addWidget(self.queue_button)
        buttons_layout.addWidget(self.pause_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.stop_ramp_button)

        # right side: live plot with run info, axis selectors and refresh controls
        self.plot_panel = LivePlotPanel()
        self.plot_canvas = self.plot_panel.canvas
        main_layout.addWidget(self.plot_panel, 2)

        self.add_dimension()  # a measurement has at least one dimension
        self.update_run_estimate()
        self.update_advanced_button()

    # ----- dimensions -----
    def add_dimension(self):
        """Add a sweep box as the new outermost (slowest) axis, above the existing ones."""
        if len(self.dimension_boxes) >= MAX_DIMENSIONS:
            return
        box = SweepDimensionBox()
        box.set_root(self.services.registry.parameters())
        box.changed.connect(self.update_run_estimate)
        box.changed.connect(self._update_markers)
        # the progress bar sits under the box, outside it, so it stays active while the box is greyed out
        box.progress_bar = QProgressBar()
        box.progress_bar.setFormat("%v / %m")
        box.progress_bar.setVisible(False)
        box.container = QWidget()
        container_layout = QVBoxLayout(box.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(2)
        container_layout.addWidget(box)
        container_layout.addWidget(box.progress_bar)
        self.dimension_boxes.insert(0, box)
        self.dimensions_layout.insertWidget(0, box.container)
        self._refresh_dimension_titles()
        self.update_run_estimate()

    def remove_dimension(self):
        """Remove the outermost (slowest) axis. Without any axis the measured parameters are acquired once."""
        if not self.dimension_boxes:
            return
        box = self.dimension_boxes.pop(0)
        self.dimensions_layout.removeWidget(box.container)
        box.container.hide()
        if box in self._run_boxes:  # its progress bar is still read until the run ends
            self._retired.append(box.container)
        else:
            box.container.deleteLater()
        self._refresh_dimension_titles()
        self.update_run_estimate()

    def _refresh_dimension_titles(self):
        """Title each box with its role in the dond loop nest and update the add/remove buttons."""
        count = len(self.dimension_boxes)
        for index, box in enumerate(self.dimension_boxes, start=1):
            if count == 1:
                title = "Sweep"
            elif index == 1:
                title = f"Axis 1 of {count} \u2013 outermost loop (slowest)"
            elif index == count:
                title = f"Axis {index} of {count} \u2013 innermost loop (fastest)"
            else:
                title = f"Axis {index} of {count}"
            box.set_title(title)
        self.snake_checkbox.setVisible(count == 2)  # a snake needs an outer and an inner axis
        self.back_forth_checkbox.setVisible(count == 1)  # back and forth is for a single axis
        self.add_dimension_button.setEnabled(count < MAX_DIMENSIONS)
        self.add_dimension_button.setText(f"Add dimension ({count}/{MAX_DIMENSIONS})")
        self.remove_dimension_button.setEnabled(count > 0)
        self.no_axis_label.setVisible(count == 0)
        if hasattr(self, "advanced_button"):
            self.update_advanced_button()

    # ----- run estimate -----
    def update_run_estimate(self):
        """Show the estimated run time on the Run button (from the points and delays of all axes)."""
        axes = [box.axis_estimate() for box in self.dimension_boxes]
        named = bool(self.measurement_name_input.text().strip())
        if not named and self._run_state == IDLE:
            self.run_button.setToolTip("Give the measurement a name to run it.")
        if not axes or any(axis is None for axis in axes):
            self.run_button.setText("Run")
            if named:
                self.run_button.setToolTip("A single acquisition: there is no sweep axis." if not axes
                                           else "Complete the sweep fields to see the estimated run time.")
            return
        repeat = self.repeat_count()
        seconds = recipes.estimate(self.get_state(), recipes.rate_lookup(self.services.registry))
        if seconds is None:  # a field the estimate needs is not a number yet
            self.run_button.setText("Run")
            return
        points = 1
        for count, _ in axes:
            points *= count
        times = f" x {repeat} repetitions" if repeat > 1 else ""
        self.run_button.setText(f"Run (\u2248 {format_estimate(seconds)})")
        if named or self._run_state != IDLE:
            self.run_button.setToolTip(
                f"{points} points{times}. Estimated from the sweep delays and the time to ramp the swept parameters "
                "(those with a maximum ramp rate, set in the Parameter explorer). The first move to the start values "
                "and the time the instruments take to measure are not included."
            )

    # ----- running state -----
    def set_running(self, running, progress=None, axis_sizes=()):
        """Lock the sweep boxes and measured parameters while a measurement runs.

        ``progress`` (RunProgress) and ``axis_sizes`` (points of each axis, outermost first) drive
        the progress bar shown under each sweep box.
        """
        self._running = running
        self._progress = progress if running else None
        self._axis_sizes = list(axis_sizes) if running else []
        if running:
            self._run_boxes = list(self.dimension_boxes)
            self._run_ramp = self.ramp_checkbox.isChecked()
            for box, size in zip(self._run_boxes, self._axis_sizes):
                box.progress_bar.setMaximum(size)
                box.progress_bar.setValue(0)
                box.progress_bar.setVisible(True)
            self._progress_timer.start(200)
        else:
            self._progress_timer.stop()
            for box in self._run_boxes:
                box.progress_bar.setVisible(False)
            self._run_boxes = []
            for container in self._retired:
                container.deleteLater()
            self._retired = []
        self._refresh_lock()

    def _refresh_lock(self):
        """While a measurement runs, the fields stay editable: they are where the next setup is prepared (the run in
        progress was built when it started and does not follow them). Only its axis bars and Run follow the run."""
        self.run_hint.setVisible(self._running)
        self._refresh_dimension_titles()
        self._update_run_enabled()

    # ----- advanced settings (the dond options) -----
    def axis_options(self):
        """[(get_after_set, actions)] of the axes, outermost first."""
        return [(box.get_after_set, box.actions) for box in self.dimension_boxes]

    def update_advanced_button(self):
        """The button says how many things differ from the defaults; its tooltip lists them."""
        items = describe_changes(normalise_advanced(self.advanced), self.axis_options())
        self.advanced_button.setText(f"Advanced settings ({len(items)})..." if items else "Advanced settings...")
        self.advanced_button.setToolTip(
            "dond options: actions, read back after setting, additional setpoints, several datasets, write period, "
            "threads, cache.\n" + ("\n".join(items) if items else "All at their defaults."))

    def open_advanced(self):
        """The advanced settings dialog; what is accepted is kept in the tab (and so in sessions, recipes and snapshots)."""
        measured = [entry.get("alias") or entry["path"][0] for entry in self.measured_box.get_state() if entry.get("path")]
        titles = [box.title() for box in self.dimension_boxes]
        dialog = AdvancedDialog(
            self.tab, self.advanced, [(box.get_after_set, box.actions) for box in self.dimension_boxes], titles,
            gettable=[name for name, p in self.services.registry.parameters().items() if getattr(p, "gettable", False)],
            axis_parameters=[[p.name for p in self._axis_parameters(box)] for box in self.dimension_boxes],
            measured=measured,
            settable=[name for name, p in self.services.registry.parameters().items() if getattr(p, "settable", False)],
        )
        if dialog.exec():
            self.advanced, axes = dialog.result()
            for box, (get_after_set, actions) in zip(self.dimension_boxes, axes):
                box.get_after_set, box.actions = get_after_set, actions
            self.update_advanced_button()

    @staticmethod
    def _axis_parameters(box):
        """The experiment parameters an axis sets (two for a TogetherSweep), as far as they are selected."""
        selectors = box.together_selectors if box.sweep_class() == "TogetherSweep" else [box.component_selector]
        return [p for p in (s.parameter() for s in selectors) if p is not None]

    # ----- the queue -----
    def add_to_queue(self):
        """Add the fields, as a recipe, at the end of the queue."""
        queue = self.services.queue
        item = queue.add(self.get_state())
        if item is not None:
            self.services.status.show(f"Added '{item.title}' to the queue ({len(queue.items)} items).", 4000)

    def edit_queue_item(self, item):
        """Load the recipe of a queue item in the fields, to change it."""
        problems = self.set_state(item.state)
        self._editing = item
        self.edit_banner_label.setText(f"Editing queue item '{item.title}'")
        self.edit_banner.setVisible(True)
        if problems:
            self.services.status.show("Not available now: " + "; ".join(problems), 6000)

    def update_edited_item(self):
        if self._editing is not None and self.services.queue.update(self._editing, self.get_state()):
            self.end_editing()

    def replace_queue_item(self, item):
        if self.services.queue.update(item, self.get_state()):
            self.services.status.show(f"Replaced '{item.title}' by the current setup.", 4000)

    def end_editing(self):
        self._editing = None
        self.edit_banner.setVisible(False)

    def _on_queue_state(self, state):
        self._queue_active = state != QUEUE_IDLE
        self._refresh_lock()

    def _on_queue_changed(self):
        item = self._editing  # the fields are the queue's once the item runs
        if item is not None and (item not in self.services.queue.items or item.status == RUNNING_ITEM):
            self.end_editing()

    def _update_run_enabled(self):
        """Run is possible when no measurement is going on and the measurement has a name."""
        named = bool(self.measurement_name_input.text().strip())
        self.run_button.setEnabled(self._run_state == IDLE and named and not self._queue_active)
        if self._run_state == IDLE and not named:
            self.run_button.setToolTip("Give the measurement a name to run it.")
        else:
            self.update_run_estimate()

    # ----- the run: asking for it, and following it -----
    def request_run(self):
        """The Run button: build the request from the fields and hand it to the run controller."""
        status = self.services.status
        if self.services.station.station is None:
            status.show("Please load a station first.", 2000)
            return
        try:
            request = self.build_request()
        except ValueError as e:
            status.show(str(e), 5000)
            return
        if not self.services.run.start(request) and self.services.run.last_problem:
            QMessageBox.warning(self.run_button.window(), "The measurement was not started", self.services.run.last_problem)

    def check_setup(self):
        """The Check setup button: the dry-run report on the measurement the fields describe."""
        if self.services.station.station is None:
            self.services.status.show("Please load a station first.", 2000)
            return
        try:
            request = self.build_request()
        except ValueError as e:
            QMessageBox.warning(self.run_button.window(), "Check setup", str(e))
            return
        report = check_request(request, self.services)
        box = QMessageBox.critical if report.errors else QMessageBox.warning if report.warnings else QMessageBox.information
        box(self.run_button.window(), "Check setup", report.text() or "No problem found.")

    def build_request(self):
        """The measurement the fields describe, for the run controller. Raises ValueError with a readable message."""
        if not self.measurement_name_input.text().strip():
            raise ValueError("Give the measurement a name.")
        progress = RunProgress(0, 1)
        parameters = self.services.registry.parameters()
        namespace = build_namespace(parameters, self.services.station.station, self.services.run.wait_tools())  # shared by the actions of this run
        axis_action = lambda action: make_callable(action, "after each point of an axis", namespace)
        sweeps = self.get_sweeps(post_action=progress.step, make_action=axis_action)
        repeat = self.repeat_count()
        progress.repetitions = repeat
        measured = self.get_measured_parameters()
        if not measured:
            raise ValueError("Add at least one measured parameter.")
        options = build_options(self.advanced, parameters, namespace)
        check_run(options, [[p.name for p in swept_parameters(sweep)] for sweep in sweeps], [n for n, _ in measured])
        return RunRequest(
            sweeps=sweeps, measured=measured, progress=progress, repeat=repeat,
            experiment_name=self.experiment_name_input.text().strip() or "Sweep",
            measurement_name=self.measurement_name_input.text().strip(),
            breakout=self.breakout_checkbox.isChecked(), state=self.get_state(),
            ramp_when_finished=self._ramp_for_run, options=options, back_and_forth=self.back_and_forth_active(),
        )

    def _on_ramp_clicked(self, checked):
        if self._running:  # ticked by the user during the run: it applies to this run
            self._run_ramp = checked

    def _ramp_for_run(self):
        """Ramp to 0 at the end of the measurement in progress: the box as it was at the start, or as the user ticked it
        since (loading a recipe to prepare the next measurement does not change it)."""
        return self._run_ramp if self._running else self.ramp_checkbox.isChecked()

    def _on_run_state(self, state):
        """The buttons follow the state of the run."""
        working = state in (RUNNING, PAUSING, PAUSED)
        self._run_state = state
        self._update_run_enabled()
        self.pause_button.setEnabled(working)
        self.pause_button.setText("Resume" if state in (PAUSING, PAUSED) else "Pause")
        self.stop_button.setEnabled(working)
        self.stop_ramp_button.setEnabled(working or state == STOPPING)  # still possible once Stop was pressed

    # ----- filling in Start and Stop from the plot -----
    def _focus_changed(self, _old, new):
        """The cursor is in a Start or Stop field: a click on the plot fills it in. It stays armed while the focus is
        on the plot, and goes when the focus goes anywhere else."""
        for box in self.dimension_boxes:
            for edit, word, selector in box.pick_fields():
                if new is edit:
                    self._pick_target = (edit, word, selector, box)
                    self.plot_panel.set_pick_target(f"{word} of {box.title()}")
                    self._update_markers()
                    return
        if new is None or new is self.plot_panel or self.plot_panel.isAncestorOf(new):
            return  # the click on the plot itself
        self._pick_target = None
        self.plot_panel.set_pick_target(None)
        self.plot_panel.set_markers(None, None)

    def _update_markers(self):
        """The Start and Stop of the axis being filled in, as lines on the plot."""
        target = self._pick_target
        if target is None:
            return
        _edit, _word, selector, box = target
        parameter = selector.parameter()
        if parameter is None or box not in self.dimension_boxes:
            self.plot_panel.set_markers(None, None)
            return
        marks = []
        for edit, word, other in box.pick_fields():
            if other is selector:
                try:
                    marks.append((word, float(edit.text())))
                except ValueError:
                    pass
        self.plot_panel.set_markers(getattr(parameter, "register_name", parameter.name), marks)

    def _pick_parameter(self, xname, word):
        """The parameter the armed field belongs to when the x axis of the plot is that parameter, else None (after telling
        the user why)."""
        window = self.run_button.window()
        parameter = self._pick_target[2].parameter()
        if parameter is None:
            QMessageBox.warning(window, "Fill in from the plot", f"Select the sweep component of this axis first: {word} "
                                "is the value of a parameter.")
            return None
        if getattr(parameter, "register_name", parameter.name) != xname:
            QMessageBox.warning(
                window, "Wrong X axis",
                f"The X axis of the plot is '{xname or 'nothing'}' but {word} is a value of '{parameter.name}'. "
                f"Choose '{parameter.name}' as the X axis of the plot (and the data must be a sweep of it), then pick "
                "again. Nothing was changed.")
            return None
        return parameter

    def _on_range_picked(self, start, stop, xname):
        """A range was dragged on the plot: it becomes the Start and the Stop of the armed axis (the direction of the
        drag is kept: the start is where the button went down)."""
        if self._pick_target is None:
            return
        _edit, word, selector, box = self._pick_target
        if self._pick_parameter(xname, word) is None:
            return
        fields = {w.rstrip("12"): e for e, w, other in box.pick_fields() if other is selector}
        if "Start" in fields and "Stop" in fields:
            fields["Start"].setText(f"{start:.6g}")
            fields["Stop"].setText(f"{stop:.6g}")

    def _limit_info(self, xname):
        """(name, minimum, maximum) of the safe limits of the experiment parameter on the x axis, when they can be set."""
        found = self._experiment_parameter(xname)
        if found is None:
            return None
        name, definition = found
        return (name, definition.min_value, definition.max_value) if definition.kind == "instrument" else None

    def _experiment_parameter(self, xname):
        registry = self.services.registry
        for name, parameter in registry.parameters().items():
            if getattr(parameter, "register_name", name) == xname and name in registry.definitions:
                return name, registry.definitions[name]
        return None

    def _on_limit_requested(self, xname, which, value):
        """Right click on the plot: set the safe maximum or minimum of the parameter on the x axis (what the Parameter
        explorer's Edit... sets). Asked first: it is a safety setting."""
        found = self._experiment_parameter(xname)
        if found is None:
            return
        name, definition = found
        word = "maximum" if which == "max" else "minimum"
        unit = f" {definition.unit}" if definition.unit else ""
        window = self.run_button.window()
        old = definition.max_value if which == "max" else definition.min_value
        answer = QMessageBox.question(
            window, "Safe limit", f"Set the safe {word} of {name} to {value:.6g}{unit}?\n\nNow: "
            + (f"{old:g}{unit}" if old is not None else "no limit") + "\nSweeps and sets beyond it are refused.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        changed = copy.copy(definition)
        if which == "max":
            changed.max_value = value
        else:
            changed.min_value = value
        try:
            self.services.registry.update(changed)
        except ValueError as e:
            QMessageBox.warning(window, "Safe limit", str(e))
            return
        self.services.status.show(f"Safe {word} of {name} set to {value:.6g}{unit}.", 5000)

    def _on_value_picked(self, value, xname):
        """A value was picked on the plot: it goes in the armed field, if the x axis of the plot is the swept parameter."""
        if self._pick_target is None:
            return
        edit, word, _selector, _box = self._pick_target
        if self._pick_parameter(xname, word) is None:
            return
        edit.setText(f"{value:.6g}")
        edit.setFocus()  # still armed: the next click can fill the other end

    def _apply_plot_memory(self):
        self.plot_panel.set_past_cache_limit(self.services.settings.past_cache_mb * 2**20)

    def _on_run_started(self, session):
        self.set_running(True, session.progress, session.axis_sizes)  # greys out the inputs
        self.plot_panel.begin_run(session.db_file, session.measurement_name, session.progress, session.dataset_names)

    def _on_run_finished(self, _session):
        self.set_running(False)  # unlock the inputs
        self.plot_panel.end_run()  # stops the clocks and refreshes the plot one last time

    def _on_parameters_changed(self):
        self.populate_parameters()
        self.update_breakout_availability()
        self.update_run_estimate()  # the ramp rates may have changed

    def register_session_fields(self, fields):
        """The entries of this tab that are remembered between sessions."""
        fields.register("measurement/state", self.get_state, self.restore_state)
        plot = self.plot_panel
        fields.register("plot/auto_refresh", plot.auto_checkbox.isChecked, plot.auto_checkbox.setChecked)
        fields.register("plot/refresh_seconds", plot.refresh_spin.value, plot.refresh_spin.setValue)
        fields.register("plot/past_curves", plot.past_spin.value, plot.past_spin.setValue)
        fields.register("plot/x_factor", plot.x_factor.text, plot.x_factor.setText)
        fields.register("plot/y_factor", plot.y_factor.text, plot.y_factor.setText)
        fields.register("plot/derivative", plot.derivative_button.isChecked, plot.derivative_button.setChecked)

    def shutdown(self):
        self.plot_panel.shutdown()

    def _update_axis_progress(self):
        """One bar per axis: position of the point in progress within that axis."""
        if self._progress is None:
            return
        positions = axis_positions(self._progress.run_done(), self._axis_sizes)
        for box, position in zip(self._run_boxes, positions):
            box.progress_bar.setValue(position)

    def get_sweeps(self, post_action=None, make_action=None):
        """QCoDeS sweeps in dond order (outermost/slowest first, innermost/fastest last).

        ``post_action`` (optional callable) is attached to the innermost sweep: dond calls it
        once per measured point, which is how the run progress is counted. ``make_action`` turns the actions of the
        axes (advanced settings) into callables.

        Raises ValueError with a readable message if a field is invalid or a parameter is
        swept twice.
        """
        sweeps = []
        multi = len(self.dimension_boxes) > 1
        last = len(self.dimension_boxes) - 1
        for index, box in enumerate(self.dimension_boxes, start=1):
            try:
                sweeps.append(box.get_sweep(post_action if index - 1 == last else None, make_action))
            except ValueError as e:
                raise ValueError(f"Axis {index}: {e}" if multi else str(e)) from None
        seen = {}
        for index, sweep in enumerate(sweeps, start=1):
            for sub in getattr(sweep, "sweeps", [sweep]):
                self._check_limits(sub, f"Axis {index}: " if multi else "")
                if id(sub.param) in seen:
                    raise ValueError(
                        f"{sub.param.full_name} is swept in axes {seen[id(sub.param)]} and {index}."
                    )
                seen[id(sub.param)] = index
        if self.snake_active():
            sweeps[-1] = make_snake(sweeps[-1])  # after the limit checks: they are done on the real values
        return sweeps

    def snake_active(self):
        """A snake sweep is asked for (it needs exactly two axes)."""
        return len(self.dimension_boxes) == 2 and self.snake_checkbox.isChecked()

    def back_and_forth_active(self):
        """Every other repetition sweeps backwards: one axis, Repeat ticked and the option ticked."""
        return (len(self.dimension_boxes) == 1 and self.repeat_checkbox.isChecked()
                and self.back_forth_checkbox.isChecked())

    def repeat_count(self):
        """How many times the measurement runs (1 when repeating is off)."""
        return self.repeat_spin.value() if self.repeat_checkbox.isChecked() else 1

    def update_breakout_availability(self):
        """The breakout option needs at least one experiment parameter with a breakout condition."""
        items = self.services.registry.breakout_items()
        self.breakout_checkbox.setEnabled(bool(items))
        if items:
            conditions = "\n".join(d.breakout.describe(d.name) for d, _ in items)
            when = ("all of these are true at the same time" if self.services.settings.breakout_mode == "all"
                    else "one of these is true")
            self.breakout_checkbox.setToolTip(f"Stop the measurement as soon as {when} (Settings > Measurement):\n" + conditions)
        else:
            self.breakout_checkbox.setChecked(False)
            self.breakout_checkbox.setToolTip("Define a breakout condition on an experiment parameter in the Parameter explorer.")

    @staticmethod
    def _check_limits(sweep, prefix):
        """Refuse a sweep that leaves the safe limits of its parameter, before anything is set."""
        points = sweep.get_setpoints()
        for value in (min(points), max(points)):
            try:
                sweep.param.validate(float(value))
            except (ValueError, TypeError) as e:
                raise ValueError(f"{prefix}{sweep.param.full_name}: {e}") from None

    # ----- station -----
    def populate_parameters(self):
        """Fill every selector (sweep axes, measured parameters) with the experiment parameters."""
        components = self.services.registry.parameters()
        for box in self.dimension_boxes:
            box.set_root(components)
        self.measured_box.refresh()
        self._apply_pending_state()

    # ----- saving and restoring the setup -----
    def get_state(self):
        """The whole tab as plain data (JSON-compatible): names, sweeps (outermost first), measured parameters."""
        return {
            "experiment_name": self.experiment_name_input.text(),
            "measurement_name": self.measurement_name_input.text(),
            "breakout": self.breakout_checkbox.isChecked(),
            "ramp_to_zero": self.ramp_checkbox.isChecked(),
            "snake": self.snake_checkbox.isChecked(),
            "back_and_forth": self.back_forth_checkbox.isChecked(),
            "repeat": {"enabled": self.repeat_checkbox.isChecked(), "times": self.repeat_spin.value()},
            "dimensions": [box.get_state() for box in self.dimension_boxes],
            "measured": self.measured_box.get_state(),
            "advanced": copy.deepcopy(self.advanced),
        }

    def set_state(self, state):
        """Set the tab up from ``get_state()`` data without running anything.

        The experiment parameters it uses must exist already. Returns the problems found (parameters
        that are not available): the rest is set up anyway.
        """
        problems = []
        self.advanced = normalise_advanced(state.get("advanced"))  # older states have none: the defaults
        if "experiment_name" in state:
            self.experiment_name_input.setText(state["experiment_name"])
        if "measurement_name" in state:
            self.measurement_name_input.setText(state["measurement_name"])
        dimensions = state.get("dimensions") or []
        if "dimensions" in state:  # an empty list is a measurement without any axis
            wanted = min(len(dimensions), MAX_DIMENSIONS)
            while len(self.dimension_boxes) < wanted:
                self.add_dimension()
            while len(self.dimension_boxes) > wanted:
                self.remove_dimension()
            for box, dimension in zip(self.dimension_boxes, dimensions):
                problems += box.set_state(dimension)
        if "measured" in state:
            problems += self.measured_box.set_state(state["measured"])
        if state.get("breakout") and self.breakout_checkbox.isEnabled():
            self.breakout_checkbox.setChecked(True)
        if "ramp_to_zero" in state:
            self.ramp_checkbox.setChecked(bool(state["ramp_to_zero"]))
        if "snake" in state:
            self.snake_checkbox.setChecked(bool(state["snake"]))
        self.back_forth_checkbox.setChecked(bool(state.get("back_and_forth", False)))  # not in older states: off
        repeat = state.get("repeat") or {}
        if "times" in repeat:
            self.repeat_spin.setValue(int(repeat["times"]))
        if "enabled" in repeat:
            self.repeat_checkbox.setChecked(bool(repeat["enabled"]))
        self.update_run_estimate()
        self._refresh_lock()
        self.update_advanced_button()
        return problems

    def restore_state(self, state):
        """Set the tab up from a saved session: like ``set_state``, but the parameters that are not available
        yet (the instruments are not loaded) are selected as soon as they become available."""
        problems = self.set_state(state)
        self._pending_state = state if problems else None
        return problems

    def _apply_pending_state(self):
        state = self._pending_state
        if not state:
            return
        dimensions = state.get("dimensions") or []
        if len(dimensions) != len(self.dimension_boxes):
            self._pending_state = None  # the user changed the layout meanwhile: do not interfere
            return
        unresolved = sum(box.fill_missing_components(dim) for box, dim in zip(self.dimension_boxes, dimensions))
        if not unresolved:
            self._pending_state = None

    # ----- measured parameters -----
    def add_measured(self, path, alias=""):
        """Add a measured parameter (the name of its experiment parameter, and an alias)."""
        return self.measured_box.add(path, alias)

    def get_measured_parameters(self):
        """[(name in the dataset, parameter)] in list order. Raises ValueError if one is not available."""
        return self.measured_box.measured()
