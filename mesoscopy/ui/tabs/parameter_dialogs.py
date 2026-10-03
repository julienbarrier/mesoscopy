"""Pop-up to define or edit an experiment parameter."""
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
)

from mesoscopy.core.experiment_parameters import OPERATORS, Breakout, ParameterDefinition
from mesoscopy.ui.tabs.component_selector import ComponentSelector, is_gettable


class ExperimentParameterDialog(QDialog):
    """Name, unit and, depending on the kind of parameter, gain, safe limits, maximum ramp rate and a
    breakout condition.

    kind "instrument": a parameter of an instrument (``source`` is its path, ``settable`` whether it
    can be set: gain, limits and ramp rate only matter for settable ones).
    kind "derived": a get-only parameter computed from an expression of other experiment parameters.
    kind "trace": an array-valued parameter of an instrument, measured over an axis that is given here (start, stop and
    number of points, or the values of another parameter). A trace of a driver (kind "instrument", ``trace_axes`` the
    names of its axes) needs nothing: it is measured as it is.
    """

    def __init__(self, parent, registry, kind, definition=None, source=None, source_text="", settable=True,
                 default_name="", default_unit="", trace_axes="", components=None):
        super().__init__(parent)
        self._registry = registry
        self._native_trace = bool(trace_axes)  # a trace of a driver: measured as it is, with its own axis
        self._components = components or {}
        self._kind = kind
        self._source = list(source or [])
        self._editing = definition is not None
        self._origin = definition.origin if definition is not None else "user"
        self._result = None
        self.setWindowTitle("Edit experiment parameter" if self._editing else "New experiment parameter")
        self.setMinimumWidth(460)
        d = definition or ParameterDefinition(name=default_name, unit=default_unit)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.name_edit = QLineEdit(d.name)
        self.name_edit.setToolTip("Name of the parameter at the root of the station (letters, digits, underscore)")
        self.name_edit.setReadOnly(self._editing)  # other parameters may use the name
        form.addRow("Name:", self.name_edit)

        if kind in ("instrument", "root", "trace"):
            source_label = QLabel(source_text or ".".join(d.source))
            source_label.setWordWrap(True)
            form.addRow("Source:", source_label)
        else:
            self.expression_edit = QLineEdit(d.expression)
            self.expression_edit.setPlaceholderText("e.g. 0.5 * (vtop + vback)")
            form.addRow("Expression:", self.expression_edit)
            names = ", ".join(sorted(n for n in registry.definitions if n != d.name)) or "none yet"
            hint = QLabel(f"Use experiment parameters ({names}), np (numpy) and const (scipy.constants, "
                          "e.g. const.e). The parameter can be read, not set.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray; font-size: 0.9em;")
            form.addRow("", hint)

        self.unit_edit = QLineEdit(d.unit or default_unit)
        if kind == "root":  # declared in the station file: used as it is, only the breakout condition can be set
            self.unit_edit.setReadOnly(True)
            note = QLabel("Declared in the station file and used as it is. Only the breakout condition can be changed.")
            note.setWordWrap(True)
            note.setStyleSheet("color: gray; font-size: 0.9em;")
            form.addRow("", note)
        form.addRow("Unit:", self.unit_edit)

        self.gain_edit = self.min_edit = self.max_edit = self.ramp_edit = None
        self.axis_widgets = {}
        if self._native_trace:
            note = QLabel(f"A trace of the driver: measured as it is, with its axis ({trace_axes}).")
            note.setWordWrap(True)
            note.setStyleSheet("color: gray; font-size: 0.9em;")
            form.addRow("", note)
        if kind == "trace":
            self._add_axis_fields(form, d)
        if kind == "instrument" and not self._native_trace:
            self.gain_edit = QLineEdit(f"{d.gain:g}")
            self.gain_edit.setToolTip("value = source value x gain (e.g. a voltage divider ratio)")
            form.addRow("Gain:", self.gain_edit)
            if settable:
                self.min_edit = QLineEdit("" if d.min_value is None else f"{d.min_value:g}")
                self.max_edit = QLineEdit("" if d.max_value is None else f"{d.max_value:g}")
                limits = QHBoxLayout()
                limits.addWidget(QLabel("min"))
                limits.addWidget(self.min_edit)
                limits.addWidget(QLabel("max"))
                limits.addWidget(self.max_edit)
                form.addRow("Safe limits:", limits)
                self.ramp_edit = QLineEdit("" if d.max_ramp_rate is None else f"{d.max_ramp_rate:g}")
                self.ramp_edit.setToolTip("Largest allowed change per second (blank: no limit)")
                self.ramp_label = QLabel("Max ramp rate (unit/s):")
                form.addRow(self.ramp_label, self.ramp_edit)
                self.unit_edit.textChanged.connect(self._update_ramp_label)
                self._update_ramp_label()

        # breakout condition
        self.breakout_group = QGroupBox("Use as a breakout condition")
        self.breakout_group.setCheckable(True)
        self.breakout_group.setChecked(d.breakout.enabled)
        self.breakout_group.setVisible(kind != "trace" and not self._native_trace)  # an array is no breakout condition
        breakout_layout = QHBoxLayout(self.breakout_group)
        breakout_layout.addWidget(QLabel("Stop the measurement when"))
        self.abs_checkbox = QCheckBox("absolute value")
        self.abs_checkbox.setChecked(d.breakout.absolute)
        self.operator_combo = QComboBox()
        self.operator_combo.addItems(list(OPERATORS))
        self.operator_combo.setCurrentText(d.breakout.operator)
        self.threshold_edit = QLineEdit(f"{d.breakout.threshold:g}")
        self.threshold_edit.setMaximumWidth(110)
        breakout_layout.addWidget(self.abs_checkbox)
        breakout_layout.addWidget(self.operator_combo)
        breakout_layout.addWidget(self.threshold_edit)
        breakout_layout.addStretch()
        layout.addWidget(self.breakout_group)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c00;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_axis_fields(self, form, d):
        """The axis of a user-defined trace: start, stop and points, or the values of another parameter."""
        self.axis_kind_combo = QComboBox()
        self.axis_kind_combo.addItem("Start, stop and number of points", "linspace")
        self.axis_kind_combo.addItem("Values of another parameter", "parameter")
        self.axis_kind_combo.setCurrentIndex(self.axis_kind_combo.findData(d.axis_kind))
        form.addRow("Axis:", self.axis_kind_combo)
        self.axis_name_edit, self.axis_unit_edit = QLineEdit(d.axis_name), QLineEdit(d.axis_unit)
        self.axis_name_edit.setPlaceholderText(f"{d.name or 'trace'}_axis")
        names = QHBoxLayout()
        names.addWidget(self.axis_name_edit)
        names.addWidget(QLabel("unit"))
        names.addWidget(self.axis_unit_edit)
        form.addRow("Axis name:", names)
        self.axis_start_edit, self.axis_stop_edit = QLineEdit(f"{d.axis_start:g}"), QLineEdit(f"{d.axis_stop:g}")
        self.axis_points_edit = QLineEdit(str(d.axis_points))
        linspace = QWidget()
        row = QHBoxLayout(linspace)
        row.setContentsMargins(0, 0, 0, 0)
        for label, edit in (("start", self.axis_start_edit), ("stop", self.axis_stop_edit),
                            ("points", self.axis_points_edit)):
            row.addWidget(QLabel(label))
            row.addWidget(edit)
        form.addRow("", linspace)
        self.axis_selector = ComponentSelector(param_filter=is_gettable, empty_text="No instruments loaded")
        self.axis_selector.set_root(self._components)
        if d.axis_source:
            self.axis_selector.set_path(d.axis_source)
        form.addRow("", self.axis_selector)
        self.axis_kind_combo.currentIndexChanged.connect(self._update_axis_fields)
        self._update_axis_fields()

    def _update_axis_fields(self):
        by_values = self.axis_kind_combo.currentData() == "parameter"
        self.axis_start_edit.parentWidget().setVisible(not by_values)
        self.axis_selector.setVisible(by_values)

    def _update_ramp_label(self):
        unit = self.unit_edit.text().strip() or "unit"
        self.ramp_label.setText(f"Max ramp rate ({unit}/s):")

    @staticmethod
    def _number(edit, what, allow_blank=False):
        text = edit.text().strip()
        if not text and allow_blank:
            return None
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{what} must be a number.") from None

    def _read_definition(self):
        """The definition described by the fields. Raises ValueError with a readable message."""
        breakout = Breakout(
            enabled=self.breakout_group.isChecked(),
            operator=self.operator_combo.currentText(),
            threshold=self._number(self.threshold_edit, "The breakout threshold") if self.breakout_group.isChecked() else 0.0,
            absolute=self.abs_checkbox.isChecked(),
        )
        definition = ParameterDefinition(
            name=self.name_edit.text().strip(), kind=self._kind, unit=self.unit_edit.text().strip(), breakout=breakout,
        )
        definition.origin = self._origin
        if self._kind == "derived":
            definition.expression = self.expression_edit.text().strip()
        elif self._kind == "root":
            pass
        elif self._kind == "trace":
            definition.source = self._source
            definition.axis_kind = self.axis_kind_combo.currentData()
            definition.axis_name = self.axis_name_edit.text().strip()
            definition.axis_unit = self.axis_unit_edit.text().strip()
            if definition.axis_kind == "parameter":
                definition.axis_source = self.axis_selector.path()
            else:
                definition.axis_start = self._number(self.axis_start_edit, "The axis start")
                definition.axis_stop = self._number(self.axis_stop_edit, "The axis stop")
                definition.axis_points = int(self._number(self.axis_points_edit, "The number of points"))
        elif self._native_trace:
            definition.source = self._source  # measured as it is: no gain, limits or ramp
        else:
            definition.source = self._source
            definition.gain = self._number(self.gain_edit, "The gain")
            if self.min_edit is not None:
                definition.min_value = self._number(self.min_edit, "The minimum", allow_blank=True)
                definition.max_value = self._number(self.max_edit, "The maximum", allow_blank=True)
                definition.max_ramp_rate = self._number(self.ramp_edit, "The maximum ramp rate", allow_blank=True)
        return definition

    def accept(self):
        try:
            definition = self._read_definition()
            self._registry.validate(definition, editing=self._editing)
        except ValueError as e:
            self.error_label.setText(str(e))
            return
        except Exception as e:
            self.error_label.setText(f"Unexpected error: {type(e).__name__}: {e}")
            return
        self._result = definition
        super().accept()

    def definition(self):
        """The accepted definition (None if the dialog was cancelled)."""
        return self._result
