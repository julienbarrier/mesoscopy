"""Parameter explorer tab: browse the instruments' parameters and choose the ones used in the experiment.

Left: the instrument browser. Pick an instrument, module or parameter with the cascading selector;
every parameter found is listed with its label, unit and value, a Read button, an editable Set
field and the validator, step and inter-delay QCoDeS applies when setting.
Right: the experiment parameters. These are the only parameters the Sweep tab offers. Each is a
root-level parameter of the station built from an instrument parameter (with name, gain, safe
limits, maximum ramp rate and optional breakout condition) or computed from other experiment
parameters (get-only).
"""
from datetime import datetime

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from mesoscopy.core.gateway import USER, parameter_instruments
from mesoscopy.core.trace_parameter import is_trace, trace_axis_names
from mesoscopy.core.experiment_parameters import resolve_source
from mesoscopy.core.parameter_io import (
    MAX_PARAMETERS, cached_value, collect_parameters, describe_inter_delay, describe_step,
    describe_validator, format_value, group_members, parameter_label, parameter_unit, parse_value,
)
from mesoscopy.ui.tabs.component_selector import ComponentSelector
from mesoscopy.ui.tabs.parameter_dialogs import ExperimentParameterDialog
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold

GROUP_COLOR = QColor(128, 128, 128, 40)  # background of the rows that are read and set together
COLUMNS = ("", "Parameter", "Label", "Unit", "Value", "", "Set", "Validator", "Step", "Inter-delay")
COL_USED, COL_NAME, COL_LABEL, COL_UNIT, COL_VALUE, COL_READ, COL_SET, COL_VALS, COL_STEP, COL_DELAY = range(10)
EXP_COLUMNS = ("Name", "Source", "Unit", "Gain", "Safe range", "Max ramp", "Breakout", "Status")


def _read_or_set(kind, parameter, value=None, history=None):
    """Reads, sets or restores one parameter (in a gateway thread: a set may ramp for a long time).

    A set goes through the restore history (``parameter.set_to``) so that the value it had can be put back."""
    if kind == "read":
        return parameter.get()
    if kind == "restore":
        history.restore(parameter)
    else:
        history.set(parameter, value)  # applies validators, step and inter_delay
    return cached_value(parameter)


class ParameterExplorerTab(QObject):
    def __init__(self, tab_widget, services):
        super().__init__()  # a QObject, so results from the worker thread are delivered in the GUI thread
        self.tab = tab_widget
        self.services = services
        self.registry = services.registry
        self._rows = {}      # id(parameter) -> row widgets (instrument browser)
        self._row_list = []  # (path, parameter) of each browser row, in table order
        self.setup_ui()
        # follow the services instead of being told: the experiment parameters, the station and its instruments
        self.registry.parametersChanged.connect(self.refresh_experiment_table)
        services.station.stationChanged.connect(self.populate_instruments)
        services.station.instrumentsChanged.connect(self.populate_instruments)

    # ================= layout =================
    def setup_ui(self):
        layout = QHBoxLayout()
        self.tab.setLayout(layout)
        layout.addWidget(self._build_browser(), 3)
        layout.addWidget(self._build_experiment_box(), 2)

    def _build_browser(self):
        group = QGroupBox("Instrument parameters")
        set_groupbox_title_bold(group)
        box = QVBoxLayout(group)

        top = QHBoxLayout()
        top.addWidget(QLabel("Component:"))
        self.selector = ComponentSelector()
        self.selector.selectionChanged.connect(self.rebuild_table)
        top.addWidget(self.selector)
        top.addStretch()
        self.recursive_checkbox = QCheckBox("Include sub-components")
        self.recursive_checkbox.setToolTip(f"List the parameters of everything below the selection (at most {MAX_PARAMETERS})")
        self.recursive_checkbox.toggled.connect(self.rebuild_table)
        top.addWidget(self.recursive_checkbox)
        self.read_all_button = QPushButton("Read all")
        self.read_all_button.clicked.connect(self.read_all)
        self.services.measuring.gate(self.read_all_button)
        top.addWidget(self.read_all_button)
        box.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeaderItem(COL_USED).setToolTip("✓ = already an experiment parameter")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column, width in ((COL_VALUE, 130), (COL_VALS, 170)):  # long values and validators are elided
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, width)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_browser_menu)
        self.table.itemDoubleClicked.connect(lambda item: self.add_selected_to_experiment())
        box.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add to experiment parameters...")
        self.add_button.setToolTip("Make the selected parameter available to the Sweep tab")
        self.add_button.clicked.connect(self.add_selected_to_experiment)
        self.monitor_button = QPushButton("Monitor")
        self.monitor_button.clicked.connect(self.monitor_selected)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.monitor_button)
        buttons.addStretch()
        box.addLayout(buttons)

        self.status_label = QLabel("Select an instrument or a parameter.")
        self.status_label.setWordWrap(True)
        box.addWidget(self.status_label)
        return group

    def _build_experiment_box(self):
        group = QGroupBox("Experiment parameters")
        set_groupbox_title_bold(group)
        box = QVBoxLayout(group)

        self.exp_table = QTableWidget(0, len(EXP_COLUMNS))
        self.exp_table.setHorizontalHeaderLabels(EXP_COLUMNS)
        self.exp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.exp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.exp_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.exp_table.verticalHeader().setVisible(False)
        header = self.exp_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.exp_table.horizontalHeaderItem(1).setToolTip("Instrument parameter, or the expression of a derived parameter")
        self.exp_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.exp_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.exp_table.customContextMenuRequested.connect(self._show_experiment_menu)
        self.exp_table.itemDoubleClicked.connect(lambda item: self.edit_selected())
        box.addWidget(self.exp_table, 1)

        buttons = QHBoxLayout()
        self.derived_button = QPushButton("Add derived parameter...")
        self.derived_button.setToolTip("A get-only parameter computed from other experiment parameters (e.g. n, D)")
        self.derived_button.clicked.connect(self.add_derived)
        self.edit_button = QPushButton("Edit...")
        self.edit_button.clicked.connect(self.edit_selected)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self.derived_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.remove_button)
        box.addLayout(buttons)
        self.ramp_all_button = QPushButton("Ramp all to zero")
        self.ramp_all_button.setToolTip(
            "Bring every settable experiment parameter to 0 at its maximum ramp rate (a parameter without a ramp "
            "rate is set directly). Refused while a measurement runs."
        )
        self.ramp_all_button.clicked.connect(self.ramp_all_to_zero)
        self.services.measuring.gate(self.ramp_all_button)
        box.addWidget(self.ramp_all_button)
        self.restore_button = QPushButton("Restore parameters from the station file")
        self.restore_button.setToolTip("Bring back the station-file parameters that were removed")
        self.restore_button.clicked.connect(self.restore_station_parameters)
        box.addWidget(self.restore_button)

        self.exp_status_label = QLabel("")
        self.exp_status_label.setWordWrap(True)
        box.addWidget(self.exp_status_label)
        self.refresh_experiment_table()
        return group

    # ================= station =================
    def populate_instruments(self):
        """Fill the selector from the station's instruments (the selection is kept when valid)."""
        self.selector.set_root(self.services.station.instruments())

    def shutdown(self):
        pass  # reads and sets run in the gateway's threads, which the main window waits for

    # ================= instrument browser =================
    def _set_status(self, text, error=False):
        self.status_label.setStyleSheet("color: #c00;" if error else "")
        self.status_label.setText(text)

    def _set_exp_status(self, text, error=False):
        self.exp_status_label.setStyleSheet("color: #c00;" if error else "")
        self.exp_status_label.setText(text)

    def rebuild_table(self, *_):
        """List the parameters of the selected component."""
        self.table.setRowCount(0)
        self._rows, self._row_list = {}, []
        component = self.selector.component()
        if component is None:
            self._set_status("Select an instrument or a parameter.")
            return
        found, truncated = collect_parameters(component, self.selector.path(), self.recursive_checkbox.isChecked())
        if not found:
            self._set_status("No parameters at this level: pick a sub-component, or tick 'Include sub-components'.")
            return
        self.table.setRowCount(len(found))
        for row, (path, parameter) in enumerate(found):
            self._fill_row(row, path, parameter)
        note = f" Showing the first {MAX_PARAMETERS}: select a sub-component to see the others." if truncated else ""
        self._set_status(f"{len(found)} parameters.{note} Select one and use 'Add to experiment parameters...'.")

    def _fill_row(self, row, path, parameter):
        key = id(parameter)
        self._row_list.append((path, parameter))

        def cell(column, text, tooltip=None):
            item = QTableWidgetItem(text)
            if tooltip:
                item.setToolTip(tooltip)
            self.table.setItem(row, column, item)
            return item

        defined = self.registry.find_by_source(path)
        cell(COL_USED, "✓" if defined else "", f"Experiment parameter '{defined.name}'" if defined else None)
        members = group_members(parameter)
        name_tip = parameter.full_name
        if len(members) > 1:
            others = ", ".join(m.short_name for m in members if m is not parameter)
            name_tip += f"\nGroup parameter: read and set together with {others}"
        name_item = cell(COL_NAME, parameter.full_name, name_tip)
        if len(members) > 1:
            name_item.setText(f"⛓ {parameter.full_name}")
        cell(COL_LABEL, parameter_label(parameter))
        cell(COL_UNIT, parameter_unit(parameter))
        value_item = cell(COL_VALUE, format_value(cached_value(parameter)),
                          f"{format_value(cached_value(parameter))}\n(last known value, not read yet)")
        cell(COL_VALS, describe_validator(parameter), describe_validator(parameter))
        cell(COL_STEP, describe_step(parameter))
        cell(COL_DELAY, describe_inter_delay(parameter))

        read_button = QPushButton("Read")
        read_button.setEnabled(bool(parameter.gettable))
        self.services.measuring.gate(read_button)
        read_button.clicked.connect(lambda _=False, p=parameter: self.read_parameter(p))
        self.table.setCellWidget(row, COL_READ, read_button)

        set_widget = QWidget()
        set_layout = QHBoxLayout(set_widget)
        set_layout.setContentsMargins(2, 0, 2, 0)
        set_edit = QLineEdit()
        set_edit.setMinimumWidth(110)
        set_button = QPushButton("Set")
        self.services.measuring.gate(set_edit)
        self.services.measuring.gate(set_button)
        if parameter.settable:
            set_edit.setPlaceholderText("new value")
            set_edit.returnPressed.connect(lambda p=parameter, e=set_edit: self.set_parameter(p, e.text()))
            set_button.clicked.connect(lambda _=False, p=parameter, e=set_edit: self.set_parameter(p, e.text()))
        else:
            set_edit.setPlaceholderText("read-only")
            set_edit.setEnabled(False)
            set_button.setEnabled(False)
        set_layout.addWidget(set_edit)
        set_layout.addWidget(set_button)
        self.table.setCellWidget(row, COL_SET, set_widget)

        if len(members) > 1:
            for column in (COL_USED, COL_NAME, COL_LABEL, COL_UNIT, COL_VALUE, COL_VALS, COL_STEP, COL_DELAY):
                self.table.item(row, column).setBackground(GROUP_COLOR)
        self._rows[key] = {"parameter": parameter, "row": row, "value_item": value_item,
                           "read_button": read_button, "set_edit": set_edit, "set_button": set_button}

    # ----- reading and setting -----
    def _start_task(self, kind, parameter, value=None):
        """Read or set a parameter through the instrument gateway. Returns False if the instruments are in use."""
        row = self._rows.get(id(parameter))
        if row is None:
            return False
        key = id(parameter)
        verb = {"read": "Reading", "set": "Setting", "restore": "Restoring"}[kind]
        job = self.services.gateway.submit(
            _read_or_set, kind, parameter, value, self.services.restore, kind=USER,
            instruments=parameter_instruments(parameter), label=f"{verb} {parameter.full_name}",
        )
        if job is None:
            self._set_status(self.services.gateway.last_refusal, error=True)
            return False
        row["value_item"].setText({"read": "reading...", "set": "setting...", "restore": "restoring..."}[kind])
        row["read_button"].setEnabled(False)
        row["set_button"].setEnabled(False)
        job.signals.result.connect(lambda result, k=key: self._on_task_done(k, kind, result, ""))
        job.signals.error.connect(
            lambda err, k=key: self._on_task_done(k, kind, None, f"{type(err[1]).__name__}: {err[1]}")
        )
        return True

    def read_parameter(self, parameter):
        self._start_task("read", parameter)

    def read_all(self):
        done = set()
        for row in self._rows.values():
            parameter = row["parameter"]
            if id(parameter) in done or not parameter.gettable:
                continue
            done.update(id(m) for m in group_members(parameter))  # one read updates the whole group
            if not self._start_task("read", parameter):
                break  # the instruments are in use: the reason is shown

    def set_parameter(self, parameter, text):
        """Set the typed value. It is parsed and validated first, so a bad value never reaches the instrument."""
        try:
            value = parse_value(text, parameter)
            parameter.validate(value)
        except Exception as e:
            self._set_status(f"{parameter.full_name}: {e}", error=True)
            return
        self._start_task("set", parameter, value)

    def _on_task_done(self, key, kind, value, error):
        row = self._rows.get(key)
        if row is None:  # the table was rebuilt in the meantime
            return
        parameter = row["parameter"]
        row["read_button"].setEnabled(bool(parameter.gettable))
        row["set_button"].setEnabled(bool(parameter.settable))
        stamp = datetime.now().strftime("%H:%M:%S")
        if error:
            row["value_item"].setText(format_value(cached_value(parameter)))
            self._set_status(f"{parameter.full_name}: {error}", error=True)
            return
        self.services.alarms.check_values([(parameter, value)])
        for sibling in group_members(parameter):  # a group read or set refreshes every member
            other = self._rows.get(id(sibling))
            if other is not None and other is not row:
                other["value_item"].setText(format_value(cached_value(sibling)))
                other["value_item"].setToolTip(f"{format_value(cached_value(sibling))}\nUpdated with {parameter.short_name} at {stamp}")
        row["value_item"].setText(format_value(value))
        row["value_item"].setToolTip(f"{format_value(value)}\n{ {'read': 'Read', 'set': 'Set', 'restore': 'Restored'}[kind] } at {stamp}")
        if kind == "set":
            row["set_edit"].clear()
            self._set_status(f"{parameter.full_name} set at {stamp}.")
        elif kind == "restore":
            self._set_status(f"{parameter.full_name} restored to {format_value(value)} at {stamp}.")

    # ----- browser actions -----
    def _selected_browser_row(self):
        row = self.table.currentRow()
        return self._row_list[row] if 0 <= row < len(self._row_list) else None

    def _run_dialog(self, dialog):
        return dialog.exec() == QDialog.DialogCode.Accepted

    def add_selected_to_experiment(self):
        """Open the pop-up to add the selected instrument parameter to the experiment parameters."""
        selected = self._selected_browser_row()
        if selected is None:
            self._set_status("Select a parameter in the table first.", error=True)
            return
        path, parameter = selected
        existing = self.registry.find_by_source(path)
        if existing is not None:
            self._edit_definition(existing)
            return
        name = "_".join(path)
        taken = set(self.registry.definitions)
        suffix, candidate = 2, name
        while candidate in taken:
            candidate, suffix = f"{name}_{suffix}", suffix + 1
        dialog = ExperimentParameterDialog(
            self.tab, self.registry, "instrument", source=path, source_text=parameter.full_name,
            settable=bool(parameter.settable), default_name=candidate, default_unit=parameter_unit(parameter),
            trace_axes=", ".join(trace_axis_names(parameter)) if is_trace(parameter) else "",
        )
        if self._run_dialog(dialog) and dialog.definition() is not None:
            self._apply(lambda: self.registry.add(dialog.definition()))

    def add_as_trace(self, path, parameter):
        """Pop-up to measure an array-valued instrument parameter as a trace over an axis given by the user."""
        name = "_".join(path) + "_trace"
        taken = set(self.registry.definitions)
        suffix, candidate = 2, name
        while candidate in taken:
            candidate, suffix = f"{name}_{suffix}", suffix + 1
        dialog = ExperimentParameterDialog(
            self.tab, self.registry, "trace", source=path, source_text=parameter.full_name, default_name=candidate,
            default_unit=parameter_unit(parameter), components=self.services.station.instruments(),
        )
        if self._run_dialog(dialog) and dialog.definition() is not None:
            self._apply(lambda: self.registry.add(dialog.definition()))

    def monitor_selected(self):
        selected = self._selected_browser_row()
        if selected is None:
            self._set_status("Select a parameter in the table first.", error=True)
            return
        self.monitor_parameter(selected[1])

    def toggle_alarm(self, parameter):
        """Put an alarm on the parameter, or take it off (what it does is set in the Settings)."""
        alarms = self.services.alarms
        if alarms.has(parameter):
            alarms.remove(parameter)
            self.services.status.show(f"Alarm on {parameter.full_name} removed.", 4000)
            return
        ok, message = alarms.add(parameter)
        self.services.status.show(message, 8000)
        if not ok:
            self._set_status(message, error=True)

    def _add_alarm_action(self, menu, parameter):
        text = "Remove alarm" if self.services.alarms.has(parameter) else "Add alarm"
        action = menu.addAction(text)
        action.setToolTip("Raise an alarm when the value gets close to the limits the parameter allows "
                          "(percentage and action: Settings > Alarms).")
        action.triggered.connect(lambda: self.toggle_alarm(parameter))

    def monitor_parameter(self, parameter):
        """Add the parameter to the Monitor tab."""
        self.services.station.add_monitored(parameter)
        self.services.status.show(f"{parameter.full_name} added to the monitor.", 3000)

    def _show_browser_menu(self, position):
        item = self.table.itemAt(position)
        if item is None or item.row() >= len(self._row_list):
            return
        self.table.selectRow(item.row())
        path, parameter = self._row_list[item.row()]
        monitor = self.services.station
        menu = QMenu(self.table)
        defined = self.registry.find_by_source(path)
        menu.addAction("Edit experiment parameter..." if defined else "Add to experiment parameters...") \
            .triggered.connect(self.add_selected_to_experiment)
        if parameter.gettable and not is_trace(parameter):  # any array-valued parameter can be measured as a trace
            menu.addAction("Add as trace...").triggered.connect(lambda: self.add_as_trace(path, parameter))
        self._add_restore_action(menu, parameter)
        if monitor.is_monitored(parameter):
            menu.addAction("Remove from monitor").triggered.connect(lambda: monitor.remove_monitored(parameter))
        else:
            menu.addAction("Monitor").triggered.connect(lambda: self.monitor_parameter(parameter))
        self._add_alarm_action(menu, parameter)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _add_restore_action(self, menu, parameter):
        """"Restore previous value": greyed out until a value was set (or ramped) from this tab."""
        history = self.services.restore
        has_previous = history.has_previous(parameter)
        label = "Restore previous value"
        if has_previous:
            label += f" ({format_value(history.previous_value(parameter))})"
        action = menu.addAction(label)
        action.setEnabled(has_previous and bool(parameter.settable))
        self.services.measuring.block(action)
        action.triggered.connect(lambda: self.restore_previous_value(parameter))
        return action

    def restore_previous_value(self, parameter):
        """Put back the value the parameter had before it was last set from this tab (one step at a time)."""
        row = self._rows.get(id(parameter))
        if row is not None:
            self._start_task("restore", parameter)
            return

        # a parameter that is not in the browser table (an experiment parameter): same job, status in its own line
        def done(result):
            self._set_exp_status(f"{parameter.full_name} restored to {format_value(cached_value(parameter))}.")

        job = self.services.gateway.submit(
            _read_or_set, "restore", parameter, None, self.services.restore, kind=USER,
            instruments=parameter_instruments(parameter), label=f"Restoring {parameter.full_name}",
        )
        if job is None:
            self._set_exp_status(self.services.gateway.last_refusal, error=True)
            return
        job.signals.result.connect(done)
        job.signals.error.connect(lambda err: self._set_exp_status(
            f"{parameter.full_name}: {type(err[1]).__name__}: {err[1]}", error=True))

    # ================= experiment parameters =================
    def refresh_experiment_table(self):
        """Redraw the experiment parameters from the registry (and the check marks of the browser)."""
        names = list(self.registry.definitions)
        self.exp_table.setRowCount(len(names))
        for row, name in enumerate(names):
            d = self.registry.definitions[name]
            ready = self.registry.is_available(name)
            built = self.registry.parameters().get(name)
            if d.kind == "trace" or (built is not None and is_trace(built)):
                gain, limits, ramp = "\u2014", "\u2014", "trace"
            elif d.kind == "root":
                gain, limits, ramp = "\u2014", "\u2014", "\u2014"
            elif d.kind == "instrument":
                gain = f"{d.gain:g}"
                low = "" if d.min_value is None else f"{d.min_value:g}"
                high = "" if d.max_value is None else f"{d.max_value:g}"
                limits = f"{low} … {high}" if (low or high) else "—"
                ramp = f"{d.max_ramp_rate:g} /s" if d.max_ramp_rate else "—"
            else:
                gain, limits, ramp = "—", "—", "get-only"
            breakout = d.breakout.describe(d.name) if d.breakout.enabled else "—"
            source = d.source_text() + (" (station file)" if d.origin == "station" and d.kind == "instrument" else "")
            values = (d.name, source, d.unit, gain, limits, ramp, breakout, self.registry.status(name))
            failed = bool(self.registry.error(name))
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if failed:
                    item.setForeground(QColor("#c00"))
                elif not ready:
                    item.setForeground(self.exp_table.palette().placeholderText())
                self.exp_table.setItem(row, column, item)
        self.restore_button.setVisible(self.registry.has_dismissed())
        if self.registry.last_error:
            self._set_exp_status(self.registry.last_error, error=True)
        elif not names:
            self._set_exp_status("No experiment parameters yet: select an instrument parameter on the left and add it.")
        else:
            self._set_exp_status(f"{len(names)} experiment parameters. The Sweep tab offers only these.")
        for row, (path, _) in enumerate(self._row_list):  # keep the browser's check marks current
            defined = self.registry.find_by_source(path)
            item = self.table.item(row, COL_USED)
            if item is not None:
                item.setText("✓" if defined else "")
                item.setToolTip(f"Experiment parameter '{defined.name}'" if defined else "")

    def _selected_definition(self):
        row = self.exp_table.currentRow()
        names = list(self.registry.definitions)
        return self.registry.definitions[names[row]] if 0 <= row < len(names) else None

    def _apply(self, change):
        """Run a registry change; show a message if it is refused (the registry tells the other tabs itself)."""
        try:
            change()
        except ValueError as e:  # a refused change, with a readable reason
            self._set_exp_status(str(e), error=True)
            return
        except Exception as e:  # anything unexpected is shown, never allowed to escape a Qt slot (it would abort the app)
            self._set_exp_status(f"Unexpected error: {type(e).__name__}: {e}", error=True)
            return

    # ----- ramping to 0 -----
    def ramp_all_to_zero(self):
        """Ramp every settable experiment parameter to 0 at its maximum ramp rate."""
        self._ramp(self.services.ramp.settable_parameters(), "all the settable experiment parameters")

    def ramp_to_zero(self, parameter):
        self._ramp([parameter], parameter.full_name)

    def _ramp(self, parameters, what):
        if not parameters:
            self._set_exp_status("No settable experiment parameter to ramp.", error=True)
            return

        def finished(problems):
            if problems:
                self._set_exp_status("Ramp to 0: " + "; ".join(problems), error=True)
            else:
                self._set_exp_status(f"{what} at 0.")

        started = self.services.ramp.start(parameters, finished, history=self.services.restore)
        if started:
            self._set_exp_status(f"Ramping {started} parameter(s) to 0...")

    def restore_station_parameters(self):
        self._apply(self.registry.restore_dismissed)

    def add_derived(self):
        dialog = ExperimentParameterDialog(self.tab, self.registry, "derived")
        if self._run_dialog(dialog) and dialog.definition() is not None:
            self._apply(lambda: self.registry.add(dialog.definition()))

    def edit_selected(self):
        definition = self._selected_definition()
        if definition is None:
            self._set_exp_status("Select an experiment parameter first.", error=True)
            return
        self._edit_definition(definition)

    def _edit_definition(self, definition):
        source_parameter = None
        if definition.kind == "instrument":
            source_parameter = resolve_source(self.services.station.station, definition.source)
        # without the instrument connected we cannot ask: keep every field available
        settable = bool(source_parameter.settable) if source_parameter is not None else True
        native = source_parameter is not None and is_trace(source_parameter)
        dialog = ExperimentParameterDialog(
            self.tab, self.registry, definition.kind, definition=definition, source=definition.source,
            source_text=definition.source_text(), settable=settable,
            trace_axes=", ".join(trace_axis_names(source_parameter)) if native else "",
            components=self.services.station.instruments(),
        )
        if self._run_dialog(dialog) and dialog.definition() is not None:
            self._apply(lambda: self.registry.update(dialog.definition()))

    def remove_selected(self):
        definition = self._selected_definition()
        if definition is None:
            self._set_exp_status("Select an experiment parameter first.", error=True)
            return
        self._apply(lambda: self.registry.remove(definition.name))

    def _show_experiment_menu(self, position):
        item = self.exp_table.itemAt(position)
        if item is None:
            return
        self.exp_table.selectRow(item.row())
        definition = self._selected_definition()
        monitor = self.services.station
        parameter = self.registry.parameters().get(definition.name)
        menu = QMenu(self.exp_table)
        menu.addAction("Edit...").triggered.connect(self.edit_selected)
        menu.addAction("Remove").triggered.connect(self.remove_selected)
        if parameter is not None and parameter.settable and definition.kind == "instrument":
            self.services.measuring.block(menu.addAction("Ramp to 0")).triggered.connect(lambda: self.ramp_to_zero(parameter))
            self._add_restore_action(menu, parameter)
        if parameter is not None:
            if monitor.is_monitored(parameter):
                menu.addAction("Remove from monitor").triggered.connect(lambda: monitor.remove_monitored(parameter))
            else:
                menu.addAction("Monitor").triggered.connect(lambda: self.monitor_parameter(parameter))
            self._add_alarm_action(menu, parameter)
        menu.exec(self.exp_table.viewport().mapToGlobal(position))
