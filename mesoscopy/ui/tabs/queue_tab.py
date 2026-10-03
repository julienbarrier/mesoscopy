"""Queue tab: the recipes (Measurement tab setups) that run one after another, and the controls of the run."""
import os

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from mesoscopy.core import queue_steps, recipes
from mesoscopy.core.export_python import generate_script
from mesoscopy.core.qcodes_options import effective_use_threads
from mesoscopy.core.run_progress import format_estimate
from mesoscopy.services.run_controller import PAUSED, PAUSING, RUNNING
from mesoscopy.services.run_queue import (
    DONE, FAILED, FINISHED, IDLE, RUNNING as ITEM_RUNNING, SKIPPED, STOPPED, WAITING,
)
from mesoscopy.ui.tabs.measured_box import TwoLineDelegate
from mesoscopy.ui.tabs.queue_step_dialogs import SeriesDialog, StepDialog
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold

# how each status is shown: a mark, and the colour of the item (None: the normal text colour)
STATUS_STYLE = {
    WAITING: ("○", None), ITEM_RUNNING: ("▶", "#1565c0"), DONE: ("✓", "#2e7d32"),
    STOPPED: ("■", "#e65100"), FAILED: ("✗", "#c62828"), SKIPPED: ("»", "#e65100"),
}
ROLE_ITEM = Qt.ItemDataRole.UserRole  # position of the item in the queue at the time the list was filled
PROGRESS_MS = 500


class QueueTab(QObject):
    """The Queue tab. It only shows ``services.queue`` and asks it for things: the recipes are taken from, and put
    in, the Measurement tab by that tab itself."""

    def __init__(self, tab_widget, services):
        super().__init__()
        self.tab = tab_widget
        self.services = services
        self.queue = services.queue
        self._rate_of = recipes.rate_lookup(services.registry)  # ramp times are part of the estimates
        self._items = []  # the queue items in the order of the list widget
        self.setup_ui()
        queue, run = self.queue, services.run
        queue.changed.connect(self.refresh)
        services.registry.parametersChanged.connect(self.refresh)  # ramp rates are part of the estimates
        queue.stateChanged.connect(lambda _state: self.update_controls())
        run.runStateChanged.connect(lambda _state: self.update_controls())
        services.ticker.connect_visible(self.tab, self._update_progress)  # the shared 1 Hz tick, only while the tab is shown
        self.refresh()

    # ================= layout =================
    def setup_ui(self):
        layout = QVBoxLayout(self.tab)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        middle = QHBoxLayout()
        layout.addLayout(middle, 1)

        # left: the list and its buttons
        left = QVBoxLayout()
        middle.addLayout(left, 3)
        self.list = QListWidget()
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        self.list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._order_changed))
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list, activated=self.remove_selected,
                  context=Qt.ShortcutContext.WidgetShortcut)
        left.addWidget(self.list, 1)
        self.empty_hint = QLabel("The queue is empty. Set a measurement up in the Measurement tab, then click "
                                 "\"Add to queue\" there (or \"Add current setup\" here). \"Add step\" adds waits and sets "
                                 "between the measurements.")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: gray;")
        left.addWidget(self.empty_hint)

        buttons = QHBoxLayout()
        left.addLayout(buttons)
        self.add_button = self._button(buttons, "Add current setup", self.queue.addCurrentRequested.emit,
                                       "Add the Measurement tab as it is now, as the last item of the queue.")
        self.duplicate_button = self._button(buttons, "Duplicate", self.duplicate_selected,
                                             "Copy the selected item below itself.")
        self.edit_button = self._button(buttons, "Edit...", self.edit_selected,
                                        "Load the selected item in the Measurement tab to change it.")
        self.remove_button = self._button(buttons, "Remove", self.remove_selected, "Remove the selected items (Delete).")
        self.step_button = QPushButton("Add step")  # a push button with a menu: the OS draws it, arrow included
        self.step_button.setToolTip("Add a wait (for a time, until a parameter is below, above or stable), a set, or a "
                                    "'repeat until' step to the queue, after the selected item.")
        step_menu = QMenu(self.step_button)
        for kind, label in queue_steps.KINDS.items():
            step_menu.addAction(label + ("..." if kind != "wait" else "...")).triggered.connect(
                lambda _c=False, k=kind: self.add_step(k))
        self.step_button.setMenu(step_menu)
        buttons.addWidget(self.step_button)
        self.series_button = self._button(
            buttons, "Series...", self.add_series,
            "Repeat the selected measurements for several values of a parameter (for instance a 2D map at several fields).")
        self.clear_button = self._button(buttons, "Clear finished", self.queue.clear_finished,
                                         "Remove the items that are done, stopped, skipped or failed.")
        buttons.addStretch()

        # right: the recipe of the selected item
        detail_group = QGroupBox("Recipe of the selected item")
        set_groupbox_title_bold(detail_group)
        detail_layout = QVBoxLayout(detail_group)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select an item to see its recipe.")
        detail_layout.addWidget(self.detail, 1)
        detail_buttons = QHBoxLayout()
        self.detail_edit_button = self._button(detail_buttons, "Edit in Measurement tab", self.edit_selected,
                                               "Load the recipe in the Measurement tab to change it.")
        self.replace_button = self._button(
            detail_buttons, "Replace with current setup", self._replace_selected,
            "Replace this recipe by the Measurement tab as it is now.")
        detail_buttons.addStretch()
        detail_layout.addLayout(detail_buttons)
        middle.addWidget(detail_group, 2)

        # bottom: running
        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.run_button = self._button(controls, "Run queue", self._run_queue,
                                       "Run the waiting items one after the other, from the top. During a measurement started by hand, the queue "
                                       "starts when that measurement has ended.")
        self.pause_button = self._button(controls, "Pause", self.services.run.toggle_pause,
                                         "Pause the measurement in progress after its current point, and resume.")
        self.skip_button = self._button(
            controls, "Skip", self.queue.skip,
            "End the measurement in progress cleanly (what is written stays), then go on with the next item.")
        self.stop_button = self._button(
            controls, "Stop", self.queue.stop,
            "End the measurement in progress cleanly and do not start the next items.")
        self.progress_label = QLabel("")
        controls.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(14)
        controls.addWidget(self.progress_bar, 1)

        options = QHBoxLayout()
        layout.addLayout(options)
        self.policy_checkbox = QCheckBox("Stop the queue if a measurement fails or hits a breakout condition")
        self.policy_checkbox.setChecked(self.queue.stop_on_failure)
        self.policy_checkbox.setToolTip(
            "Ticked: a measurement that fails or ends on a breakout condition (a gate leaking, for instance) ends "
            "the queue. Not ticked: the queue goes on with the next item.")
        self.policy_checkbox.toggled.connect(self._set_policy)
        options.addWidget(self.policy_checkbox)
        options.addStretch()
        self.save_button = self._button(options, "Save queue...", self.save_queue, "Save the recipes to a file.")
        self.load_button = self._button(options, "Load queue...", self.load_queue,
                                        "Replace the queue by the recipes of a file.")
        self.export_button = self._button(
            options, "Export as Python...", self.export_python,
            "Write a Python script that runs the measurements of the queue, in order, with plain QCoDeS dond(...) "
            "calls: the same runs outside the application.")

    @staticmethod
    def _button(layout, text, callback, tip=""):
        button = QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False: callback())
        layout.addWidget(button)
        return button

    # ================= the list =================
    def refresh(self):
        """Show the queue as it is, keeping the selection."""
        selected = set(map(id, self._selected_items()))
        self._items = list(self.queue.items)
        self.list.blockSignals(True)
        self.list.clear()
        for number, item in enumerate(self._items, start=1):
            mark, color = STATUS_STYLE[item.status]
            word = item.status if item.status != WAITING else "waiting"
            entry = QListWidgetItem(f"{mark} {number}  {item.title}   [{word}]\n{recipes.summary(item.state, self._rate_of)}")
            entry.setData(ROLE_ITEM, number - 1)
            entry.setToolTip(item.message or recipes.description(item.state, self._rate_of))
            if color:
                entry.setForeground(QBrush(QColor(color)))
            if item.status == ITEM_RUNNING:  # the running item stays where it is
                entry.setFlags(entry.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(entry)
            entry.setSelected(id(item) in selected)
        self.list.blockSignals(False)
        self.empty_hint.setVisible(not self._items)
        self._selection_changed()
        self.update_controls()

    def _selected_items(self):
        return [self._items[i.data(ROLE_ITEM)] for i in self.list.selectedItems()]

    def _order_changed(self):
        """The user dragged items: the list is the new order."""
        order = [self._items[self.list.item(row).data(ROLE_ITEM)] for row in range(self.list.count())]
        if order != self.queue.items:
            running = [i for i in self.queue.items if i.status == ITEM_RUNNING]
            if running and order.index(running[0]) != self.queue.items.index(running[0]):
                order = list(self.queue.items)  # nothing may take the place of the running item
            self.queue.items[:] = order
        self.queue.changed.emit()

    def _selection_changed(self):
        selected = self._selected_items()
        if len(selected) == 1:
            item = selected[0]
            text = recipes.description(item.state, self._rate_of)
            if item.message:
                text += f"\n\nResult: {item.message}"
            if item.run_ids:
                text += "\nRuns written: " + ", ".join(str(r) for r in item.run_ids)
            self.detail.setPlainText(text)
        else:
            self.detail.setPlainText(f"{len(selected)} items selected." if selected else "")
        self.update_controls()

    # ================= actions =================
    def _idle(self):
        return self.queue.state == IDLE and not self.services.run.running

    def _editable(self, items):
        """One item that is not being run: its recipe can be loaded in the Measurement tab, also during a run."""
        return len(items) == 1 and items[0].status != ITEM_RUNNING

    def duplicate_selected(self):
        for item in self._selected_items():
            self.queue.duplicate(item)

    def remove_selected(self):
        self.queue.remove(self._selected_items())

    def _parameter_names(self):
        """(readable, settable) experiment parameter names for the step dialogs."""
        parameters = self.services.registry.parameters()
        return ([n for n, p in parameters.items() if getattr(p, "gettable", False)],
                [n for n, p in parameters.items() if getattr(p, "settable", False)])

    def _insert_position(self):
        """After the last selected item, else at the end."""
        selected = self._selected_items()
        return max(self.queue.items.index(i) for i in selected) + 1 if selected else len(self.queue.items)

    def add_step(self, kind):
        readable, settable = self._parameter_names()
        dialog = StepDialog(self.tab, readable, settable, kind=kind)
        if dialog.exec():
            self.queue.insert([dialog.state()], self._insert_position())

    def add_series(self):
        selected = [i for i in self._selected_items() if not queue_steps.is_step(i.state)]
        if not selected:
            self.services.status.show("Select the measurement(s) to repeat first.", 4000)
            return
        _, settable = self._parameter_names()
        if not settable:
            self.services.status.show("There is no settable experiment parameter.", 4000)
            return
        dialog = SeriesDialog(self.tab, settable, len(selected))
        if not dialog.exec():
            return
        position = max(self.queue.items.index(i) for i in selected) + 1
        states = dialog.states([i.state for i in selected])
        if dialog.replace.isChecked():
            position -= len(selected)
            self.queue.remove(selected)
        self.queue.insert(states, position)

    def edit_selected(self):
        selected = self._selected_items()
        if not self._editable(selected):
            return
        if queue_steps.is_step(selected[0].state):  # a step is edited here, a measurement in the Measurement tab
            readable, settable = self._parameter_names()
            dialog = StepDialog(self.tab, readable, settable, state=selected[0].state)
            if dialog.exec():
                self.queue.update(selected[0], dialog.state())
            return
        self.queue.editRequested.emit(selected[0])

    def _replace_selected(self):
        selected = self._selected_items()
        if self._editable(selected) and not queue_steps.is_step(selected[0].state):
            self.queue.replaceRequested.emit(selected[0])

    def _run_queue(self):
        self.queue.start()

    def _set_policy(self, checked):
        self.queue.stop_on_failure = checked

    def _context_menu(self, position):
        if self.list.itemAt(position) is None:
            return
        selected = self._selected_items()
        single = len(selected) == 1
        running = any(i.status == ITEM_RUNNING for i in selected)
        menu = QMenu(self.list)
        actions = {}

        def add(text, callback, enabled=True):
            action = menu.addAction(text)
            action.setEnabled(enabled)
            actions[action] = callback

        add("Run only this one", lambda: self.queue.start(only=selected[0]), single and self._idle())
        add("Edit", self.edit_selected, self._editable(selected))
        add("Duplicate", self.duplicate_selected)
        add("Make wait again", lambda: self.queue.reset(selected), any(i.status in FINISHED for i in selected))
        menu.addSeparator()
        add("Remove", self.remove_selected, not running)
        chosen = menu.exec(self.list.viewport().mapToGlobal(position))
        if chosen in actions:
            actions[chosen]()

    # ================= saving the queue =================
    def _start_folder(self):
        return getattr(self.services.data, "folder", "") or os.path.expanduser("~")

    def save_queue(self):
        path, _ = QFileDialog.getSaveFileName(self.tab, "Save queue", os.path.join(self._start_folder(), "queue.json"),
                                              "Queue files (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.queue.to_text())
        except OSError as e:
            self.services.status.show(f"Cannot save the queue: {e}", 6000)
            return
        self.services.status.show(f"Queue saved to {path}.", 4000)

    def load_queue(self):
        if self.queue.active:
            self.services.status.show("The queue is running: stop it first.", 4000)
            return
        path, _ = QFileDialog.getOpenFileName(self.tab, "Load queue", self._start_folder(), "Queue files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.queue.replace_from_text(f.read())
        except (OSError, ValueError) as e:
            self.services.status.show(f"Cannot load the queue: {e}", 6000)
            return
        self.services.status.show(f"Queue loaded from {path}.", 4000)

    def _loaded_components(self):
        """The entries of the station file that are loaded (the experiment parameters the application adds at the
        root of the station are not entries of the file: the script builds them itself)."""
        declared = self.services.registry.station_config
        return [name for name in self.services.station.station.components if name in declared]

    def export_context(self):
        """What the script needs besides the recipes: the station, the database, the sample, the options in force."""
        services = self.services
        try:
            database = services.data.database_for_run()
        except ValueError:
            database = os.path.join(services.data.folder or ".", "results.db")
        return {
            "station_file": services.station.station_file, "components": self._loaded_components(),
            "database": database, "sample_name": services.data.sample_name,
            "stop_on_failure": self.queue.stop_on_failure, "breakout_mode": services.settings.breakout_mode,
            "use_threads": effective_use_threads(services.settings),
        }

    def export_python(self):
        """Write the queue as a Python script (``core/export_python``): the same measurements outside the application."""
        status = self.services.status
        if not self.queue.items:
            status.show("The queue is empty: nothing to export.", 4000)
            return
        if self.services.station.station is None or not self.services.station.station_file:
            status.show("Load a station first: the script loads the same station file.", 5000)
            return
        path, _ = QFileDialog.getSaveFileName(self.tab, "Export the queue as a Python script",
                                              os.path.join(self._start_folder(), "queue.py"), "Python files (*.py)")
        if not path:
            return
        try:
            text = generate_script([i.state for i in self.queue.items], self.export_context(),
                                   [d.to_dict() for d in self.services.registry.definitions.values()],
                                   name=os.path.basename(path))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:  # a recipe the exporter cannot write must not crash the application
            status.show(f"Cannot export the queue: {type(e).__name__}: {e}", 8000)
            return
        status.show(f"Queue exported to {path}.", 5000)

    def register_session_fields(self, fields):
        fields.register("queue/state", self.queue.to_data, self._restore)

    def _restore(self, data):
        self.queue.restore_data(data)
        self.policy_checkbox.setChecked(self.queue.stop_on_failure)

    # ================= state of the controls =================
    def update_controls(self):
        queue, run = self.queue, self.services.run
        selected = self._selected_items()
        single = len(selected) == 1
        self.run_button.setText("Run queue after current run finishes" if run.running and not queue.active else "Run queue")
        self.run_button.setEnabled(not queue.active and bool(queue.waiting()))  # also during a measurement: it follows
        self.pause_button.setEnabled(queue.active and run.state in (RUNNING, PAUSING, PAUSED))
        self.pause_button.setText("Resume" if run.state in (PAUSING, PAUSED) else "Pause")
        self.skip_button.setEnabled(queue.active and queue.current is not None and (run.running or queue.step_running))
        self.stop_button.setEnabled(queue.active)
        editable = self._editable(selected)
        self.add_button.setEnabled(True)  # the setup is prepared while a measurement runs
        self.edit_button.setEnabled(editable)
        self.detail_edit_button.setEnabled(editable)
        self.replace_button.setEnabled(editable and not (single and queue_steps.is_step(selected[0].state)))
        self.duplicate_button.setEnabled(bool(selected))
        self.series_button.setEnabled(any(not queue_steps.is_step(i.state) for i in selected))
        self.remove_button.setEnabled(bool(selected) and not any(i.status == ITEM_RUNNING for i in selected))
        self.clear_button.setEnabled(any(i.status in FINISHED for i in queue.items))
        self.save_button.setEnabled(bool(queue.items))
        self.export_button.setEnabled(bool(queue.items))
        self.load_button.setEnabled(not queue.active)
        self.policy_checkbox.setEnabled(True)
        self.list.setDragEnabled(True)
        waiting = queue.waiting()
        seconds = [recipes.estimate(i.state, self._rate_of) for i in waiting]
        known = sum(s for s in seconds if s)
        text = f"{len(queue.items)} item{'' if len(queue.items) == 1 else 's'}"
        if waiting:
            text += f", {len(waiting)} waiting" + (f" (about {format_estimate(known)})" if known else "")
        self.summary_label.setText(text)
        self._update_progress()

    def _update_progress(self):
        queue = self.queue
        if not queue.active:
            self.progress_bar.setValue(0)
            self.progress_label.setText("")
            return
        finished, total, fraction = queue.progress()
        shown = min(finished + 1, total) if total else 0
        self.progress_label.setText(f"item {shown} of {total}")
        self.progress_bar.setValue(int(1000 * (finished + fraction) / total) if total else 0)
