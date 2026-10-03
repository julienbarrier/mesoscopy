"""The "Advanced settings" dialog of the Measurement tab: the dond options (see ``core/dond_options``)."""
import copy

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from mesoscopy.core.dond_options import (
    clean_actions, compile_action, new_action, normalise_advanced, validate_datasets,
)
from mesoscopy.core.auto_actions import EXPORT_TYPES, PLOT_FORMATS
from mesoscopy.core.predefined_actions import PREDEFINED, build_action
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold

ROLE_CODE = Qt.ItemDataRole.UserRole
NAMESPACE_HELP = (
    "Python statements, run when the measurement reaches that point. Available: every experiment parameter by name "
    "(vtop() reads it, vtop(0.5) sets it, with its limits and ramp rate), station, np, time, const, and the waiting "
    "helpers wait, wait_until, wait_below, wait_above, wait_stable (they end on Stop and can time out). The actions of one "
    "measurement share their variables. It is your own code, run as it is: there is no sandbox."
)


class ActionListEditor(QGroupBox):
    """A list of named actions (each with an on/off check) and the code of the selected one."""

    def __init__(self, title, tip="", where="", parameters=None):
        """``parameters``: a function giving (readable parameter names, settable parameter names) for the pre-defined
        actions' drop-down."""
        super().__init__(title)
        self._parameters = parameters or (lambda: ([], []))
        set_groupbox_title_bold(self)
        self.where = where
        if tip:
            self.setToolTip(tip)
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        layout.addLayout(left, 1)
        self.list = QListWidget()
        self.list.setMaximumWidth(220)
        self.list.currentItemChanged.connect(self._current_changed)
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        for text, tip_text, callback in (("Add", "Add an action", self.add), ("Remove", "Remove the selected action", self.remove),
                                         ("↑", "Move up (actions run in the order of the list)", lambda: self._move(-1)),
                                         ("↓", "Move down", lambda: self._move(1))):
            button = QPushButton(text)
            button.setToolTip(tip_text)
            button.clicked.connect(lambda _c=False, f=callback: f())
            buttons.addWidget(button)
        left.addLayout(buttons)
        self.predefined_button = QPushButton("Add pre-defined")  # a push button with a menu: the OS draws it, arrow included
        self.predefined_button.setToolTip("Add a one-line action from a list (wait until a value is reached or stable, "
                                          "set a parameter). The line can be edited, and mixed with code of your own.")
        self.predefined_menu = QMenu(self.predefined_button)
        self.predefined_menu.aboutToShow.connect(self._fill_predefined_menu)
        self.predefined_button.setMenu(self.predefined_menu)
        left.addWidget(self.predefined_button)
        right = QVBoxLayout()
        layout.addLayout(right, 3)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setPlaceholderText("Python code, e.g.\nvtop(0)\ntime.sleep(2)")
        self.editor.setToolTip(NAMESPACE_HELP)
        self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.editor.textChanged.connect(self._code_edited)
        self.editor.setEnabled(False)
        right.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.check_button = QPushButton("Check")
        self.check_button.setToolTip("Compile the code of the selected action and show its first error")
        self.check_button.clicked.connect(self.check)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        row.addWidget(self.check_button)
        row.addWidget(self.message, 1)
        right.addLayout(row)
        self._current = None

    # ----- the list -----
    def set_actions(self, actions):
        self._current = None
        self.list.clear()
        for action in clean_actions(actions):
            self._add_item(action)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._current_changed(self.list.currentItem(), None)

    def _add_item(self, action):
        item = QListWidgetItem(action["name"])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
        item.setCheckState(Qt.CheckState.Checked if action["enabled"] else Qt.CheckState.Unchecked)
        item.setData(ROLE_CODE, action["code"])
        self.list.addItem(item)
        return item

    def add(self):
        names = {self.list.item(i).text() for i in range(self.list.count())}
        number = 1
        while f"action {number}" in names:
            number += 1
        item = self._add_item(new_action(f"action {number}"))
        self.list.setCurrentItem(item)
        self.editor.setFocus()

    def _fill_predefined_menu(self):
        """The menu: an entry that needs a parameter opens a drop-down of the parameters it can use."""
        menu = self.predefined_menu
        menu.clear()
        readable, settable = self._parameters()
        for entry in PREDEFINED:
            if not entry.needs:
                menu.addAction(entry.label).triggered.connect(lambda _c=False, e=entry: self._add_predefined(e))
                continue
            names = [n for n in (readable if entry.needs == "get" else settable) if n.isidentifier()]
            sub = menu.addMenu(entry.label)
            sub.setEnabled(bool(names))
            for name in names:
                sub.addAction(name).triggered.connect(lambda _c=False, e=entry, n=name: self._add_predefined(e, n))

    def _add_predefined(self, entry, parameter=""):
        item = self._add_item(build_action(entry, parameter))
        self.list.setCurrentItem(item)

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self._current = None
            self.list.takeItem(row)

    def _move(self, step):
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentItem(item)

    def _current_changed(self, item, _previous):
        self._current = item
        self.editor.blockSignals(True)
        self.editor.setPlainText(item.data(ROLE_CODE) if item is not None else "")
        self.editor.blockSignals(False)
        self.editor.setEnabled(item is not None)
        self.message.setText("")

    def _code_edited(self):
        if self._current is not None:
            self._current.setData(ROLE_CODE, self.editor.toPlainText())

    # ----- reading and checking -----
    def actions(self):
        return [new_action(self.list.item(i).text().strip() or f"action {i + 1}", self.list.item(i).data(ROLE_CODE) or "",
                           self.list.item(i).checkState() == Qt.CheckState.Checked) for i in range(self.list.count())]

    def error(self):
        """The first syntax error among the enabled actions, or None."""
        for action in self.actions():
            if action["enabled"]:
                try:
                    compile_action(action, self.where)
                except ValueError as e:
                    return str(e)
        return None

    def check(self):
        item = self._current
        if item is None:
            return
        try:
            compile_action(new_action(item.text(), item.data(ROLE_CODE) or ""), self.where)
        except ValueError as e:
            self.message.setStyleSheet("color: #c00;")
            self.message.setText(str(e))
            return
        self.message.setStyleSheet("color: #2e7d32;")
        self.message.setText("The code compiles.")


class AdvancedDialog(QDialog):
    """Edit the advanced settings. ``result()`` gives (advanced settings, [(get_after_set, actions)] per axis).

    ``axes``: [(get_after_set, actions)] of the axes now, ``titles`` their titles, ``axis_parameters`` the names of the
    experiment parameters each sets, ``gettable`` the experiment parameters that can be read, ``measured`` the names of
    the measured parameters in the dataset."""

    def __init__(self, parent, advanced, axes, titles, gettable, axis_parameters, measured, settable=()):
        super().__init__(parent)
        self.setWindowTitle("Advanced settings")
        self.resize(900, 620)
        self._advanced = normalise_advanced(copy.deepcopy(advanced))
        self._axis_parameters = axis_parameters
        self._measured = measured
        parameters = lambda: (list(gettable), list(settable))
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        # ---- before and after the measurement
        page = QWidget()
        page_layout = QVBoxLayout(page)
        hint = QLabel(NAMESPACE_HELP)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 0.9em;")
        page_layout.addWidget(hint)
        self.enter_editor = ActionListEditor(
            "Before the measurement starts (enter_actions)", "Run once, before the first point.",
            "before the measurement", parameters)
        self.exit_editor = ActionListEditor(
            "After the measurement ends (exit_actions)", "Run once, after the last point (also when it was stopped).",
            "after the measurement", parameters)
        page_layout.addWidget(self.enter_editor)
        page_layout.addWidget(self.exit_editor)
        tabs.addTab(page, "Actions")

        # ---- the axes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        axes_layout = QVBoxLayout(container)
        self.axis_checks, self.axis_editors = [], []
        if not axes:
            axes_layout.addWidget(QLabel("The measurement has no sweep axis."))
        for index, ((get_after_set, actions), title) in enumerate(zip(axes, titles), start=1):
            group = QGroupBox(f"Axis {index}: {title}")
            set_groupbox_title_bold(group)
            group_layout = QVBoxLayout(group)
            check = QCheckBox("Read the parameter back after setting it (get_after_set)")
            check.setToolTip("After each set, read the parameter and store the value read instead of the value set. "
                             "A snake axis does this always.")
            check.setChecked(bool(get_after_set))
            editor = ActionListEditor(
                "Actions after each point, before the inner loop (post_actions)",
                "Run right after this axis's parameter is set, before its delay and before the inner loop. The dond "
                "equivalent of before_inner_actions.", "after each point of axis " + str(index), parameters)
            editor.set_actions(actions)
            group_layout.addWidget(check)
            note = QLabel("The actions run right after this axis's parameter is set, before its delay and before the "
                          "inner loop (what do2d called before_inner_actions).")
            note.setWordWrap(True)
            note.setStyleSheet("color: gray; font-size: 0.9em;")
            group_layout.addWidget(note)
            group_layout.addWidget(editor)
            axes_layout.addWidget(group)
            self.axis_checks.append(check)
            self.axis_editors.append(editor)
        axes_layout.addStretch()
        scroll.setWidget(container)
        tabs.addTab(scroll, "Axes")

        # ---- setpoints and datasets
        page = QWidget()
        page_layout = QVBoxLayout(page)
        extra_group = QGroupBox("Additional setpoints (additional_setpoints)")
        set_groupbox_title_bold(extra_group)
        extra_group.setToolTip("Experiment parameters read once before the sweep and stored with every point as extra "
                               "setpoints of the dataset (a temperature, a field ...). They are not swept.")
        extra_layout = QVBoxLayout(extra_group)
        self.extra_list = QListWidget()
        self.extra_list.setMaximumHeight(130)
        for name in gettable:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in self._advanced["setpoints"] else Qt.CheckState.Unchecked)
            self.extra_list.addItem(item)
        self.extra_list.itemChanged.connect(lambda _item: self._extra_changed())
        extra_layout.addWidget(self.extra_list)
        page_layout.addWidget(extra_group)

        self.datasets_group = QGroupBox("Write several datasets (dataset_dependencies)")
        set_groupbox_title_bold(self.datasets_group)
        self.datasets_group.setCheckable(True)
        self.datasets_group.setChecked(bool(self._advanced["datasets"]))
        self.datasets_group.setToolTip(
            "Each dataset is a run of its own, with the measured parameters you tick and the setpoints they depend on. "
            "Each dataset must depend on at least one parameter of every axis and on every additional setpoint.")
        datasets_layout = QVBoxLayout(self.datasets_group)
        self.datasets_table = QTableWidget(0, 0)
        datasets_layout.addWidget(self.datasets_table, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add dataset")
        add.clicked.connect(self._add_dataset)
        remove = QPushButton("Remove dataset")
        remove.clicked.connect(self._remove_dataset)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        datasets_layout.addLayout(buttons)
        self.datasets_group.toggled.connect(self._datasets_toggled)
        page_layout.addWidget(self.datasets_group, 1)
        tabs.addTab(page, "Setpoints and datasets")

        # ---- run options
        page = QWidget()
        form = QFormLayout(page)
        self.period_edit = QLineEdit("" if self._advanced["write_period"] is None else f"{self._advanced['write_period']:g}")
        self.period_edit.setPlaceholderText("0.5 (the live plot reads what is written)")
        self.period_edit.setToolTip("Seconds between two writes of the data to the database.")
        form.addRow("Write period (s):", self.period_edit)
        self.threads_combo = self._tri_state(self._advanced["use_threads"])
        self.threads_combo.setToolTip("Measure the instruments on separate threads. Default: the Settings.")
        form.addRow("Use threads:", self.threads_combo)
        self.cache_combo = self._tri_state(self._advanced["in_memory_cache"])
        self.cache_combo.setToolTip("Keep the data in memory too (faster plotting, more memory). Off helps with very "
                                    "large traces. Default: the QCoDeS configuration.")
        form.addRow("In-memory cache:", self.cache_combo)
        self.log_edit = QLineEdit(self._advanced["log_info"])
        self.log_edit.setPlaceholderText("a message written to the QCoDeS log when the measurement starts")
        form.addRow("Log message:", self.log_edit)
        # after the run (QCoDeS' export and plot_dataset)
        self.export_combo = self._tri_state(self._advanced["export"])
        self.export_combo.setToolTip(
            "Export the data of each run when it ends, with QCoDeS' automatic export (qcodes.config.dataset.export_automatic). "
            "Default: as the QCoDeS configuration says (Settings, QCoDeS tab). Yes / No: for this measurement only.")
        form.addRow("Export the data after each run:", self.export_combo)
        self.export_type_combo = QComboBox()
        self.export_type_combo.addItem("QCoDeS setting (csv if none)", "")
        for kind in EXPORT_TYPES:
            self.export_type_combo.addItem(kind, kind)
        self.export_type_combo.setCurrentIndex(max(self.export_type_combo.findData(self._advanced["export_type"]), 0))
        self.export_type_combo.setToolTip("qcodes.config.dataset.export_type. NetCDF needs xarray and netCDF4 or h5netcdf.")
        form.addRow("Export format:", self.export_type_combo)
        self.export_path_edit = QLineEdit(self._advanced["export_path"])
        self.export_path_edit.setPlaceholderText("QCoDeS setting (a folder named after the database, next to it)")
        self.export_path_edit.setToolTip("qcodes.config.dataset.export_path. {db_location} stands for the folder of the database.")
        form.addRow("Export folder:", self.export_path_edit)
        self.plot_check = QCheckBox("Save the plots after each run")
        self.plot_check.setChecked(bool(self._advanced["save_plot"]))
        self.plot_check.setToolTip("Plot each dataset with qcodes.dataset.plot_dataset and save the figure in the export "
                                   "folder (plot_<run id>_<name>). Also done when the run was stopped or failed, if it wrote data.")
        self.plot_format_combo = QComboBox()
        for kind in PLOT_FORMATS:
            self.plot_format_combo.addItem(kind, kind)
        self.plot_format_combo.setCurrentIndex(max(self.plot_format_combo.findData(self._advanced["plot_format"]), 0))
        plot_row = QHBoxLayout()
        plot_row.addWidget(self.plot_check)
        plot_row.addWidget(self.plot_format_combo)
        plot_row.addStretch()
        form.addRow(plot_row)
        tabs.addTab(page, "Run options")

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c00;")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.enter_editor.set_actions(self._advanced["enter"])
        self.exit_editor.set_actions(self._advanced["exit"])
        self._datasets = copy.deepcopy(self._advanced["datasets"])
        self._fill_table()

    @staticmethod
    def _tri_state(value):
        combo = QComboBox()
        combo.addItem("Default", None)
        combo.addItem("Yes", True)
        combo.addItem("No", False)
        combo.setCurrentIndex(combo.findData(value))
        return combo

    # ----- the datasets table -----
    def _extra_names(self):
        return [self.extra_list.item(i).text() for i in range(self.extra_list.count())
                if self.extra_list.item(i).checkState() == Qt.CheckState.Checked]

    def _setpoint_names(self):
        """The setpoints a dataset can depend on: the swept parameters, then the additional setpoints."""
        names = []
        for parameters in self._axis_parameters:
            names += [n for n in parameters if n not in names]
        return names + [n for n in self._extra_names() if n not in names]

    def _collect_table(self):
        """The datasets as the table shows them (kept in ``self._datasets``)."""
        table = self.datasets_table
        columns = [table.horizontalHeaderItem(c).data(ROLE_CODE) for c in range(table.columnCount())]
        datasets = []
        for row in range(table.rowCount()):
            dataset = {"name": table.item(row, 0).text().strip(), "setpoints": [], "measured": []}
            for column, (kind, name) in enumerate(columns[1:], start=1):
                if table.item(row, column).checkState() == Qt.CheckState.Checked:
                    dataset["setpoints" if kind == "set" else "measured"].append(name)
            datasets.append(dataset)
        self._datasets = datasets

    def _fill_table(self):
        table = self.datasets_table
        table.blockSignals(True)
        setpoints = self._setpoint_names()
        columns = [("set", n) for n in setpoints] + [("meas", n) for n in self._measured]
        table.clear()
        table.setRowCount(len(self._datasets))
        table.setColumnCount(1 + len(columns))
        header = QTableWidgetItem("Dataset name")
        header.setData(ROLE_CODE, ("name", ""))
        table.setHorizontalHeaderItem(0, header)
        for c, (kind, name) in enumerate(columns, start=1):
            item = QTableWidgetItem(("set: " if kind == "set" else "") + name)
            item.setData(ROLE_CODE, (kind, name))
            item.setToolTip("setpoint" if kind == "set" else "measured parameter")
            table.setHorizontalHeaderItem(c, item)
        for row, dataset in enumerate(self._datasets):
            table.setItem(row, 0, QTableWidgetItem(dataset["name"]))
            for c, (kind, name) in enumerate(columns, start=1):
                cell = QTableWidgetItem()
                cell.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chosen = name in dataset["setpoints" if kind == "set" else "measured"]
                cell.setCheckState(Qt.CheckState.Checked if chosen else Qt.CheckState.Unchecked)
                table.setItem(row, c, cell)
        table.resizeColumnsToContents()
        table.blockSignals(False)
        self.datasets_group.setEnabled(True)

    def _extra_changed(self):
        if hasattr(self, "_datasets"):
            self._collect_table()
            self._fill_table()

    def _add_dataset(self):
        self._collect_table()
        self._datasets.append({"name": f"dataset {len(self._datasets) + 1}", "setpoints": self._setpoint_names(), "measured": []})
        self._fill_table()

    def _remove_dataset(self):
        self._collect_table()
        row = self.datasets_table.currentRow()
        if 0 <= row < len(self._datasets):
            del self._datasets[row]
            self._fill_table()

    def _datasets_toggled(self, on):
        if on and not self.datasets_table.rowCount():
            self._add_dataset()

    # ----- accepting -----
    def _accept(self):
        error = self._validate()
        self.error_label.setText(error or "")
        if error is None:
            self.accept()

    def _validate(self):
        for editor in (self.enter_editor, self.exit_editor, *self.axis_editors):
            error = editor.error()
            if error:
                return error
        text = self.period_edit.text().strip()
        if text:
            try:
                if float(text) <= 0:
                    raise ValueError
            except ValueError:
                return "The write period must be a positive number of seconds (or empty)."
        if self.datasets_group.isChecked():
            self._collect_table()
            return validate_datasets(self._datasets, self._axis_parameters, self._extra_names(), self._measured)
        return None

    def result(self):
        """(advanced settings, [(get_after_set, actions)] per axis) as edited."""
        if self.datasets_group.isChecked():
            self._collect_table()
        text = self.period_edit.text().strip()
        advanced = normalise_advanced({
            "enter": self.enter_editor.actions(), "exit": self.exit_editor.actions(), "setpoints": self._extra_names(),
            "datasets": self._datasets if self.datasets_group.isChecked() else [],
            "write_period": float(text) if text else None, "use_threads": self.threads_combo.currentData(),
            "in_memory_cache": self.cache_combo.currentData(), "log_info": self.log_edit.text(),
            "export": self.export_combo.currentData(), "export_type": self.export_type_combo.currentData(),
            "export_path": self.export_path_edit.text(), "save_plot": self.plot_check.isChecked(),
            "plot_format": self.plot_format_combo.currentData(),
        })
        axes = [(check.isChecked(), editor.actions()) for check, editor in zip(self.axis_checks, self.axis_editors)]
        return advanced, axes
