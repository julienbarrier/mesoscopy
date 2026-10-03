"""Dialogs of the Queue tab for the steps (see ``core/queue_steps``): one step, and a series over a parameter."""
import copy

import numpy as np
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QSpinBox,
    QVBoxLayout,
)

from mesoscopy.core import queue_steps

BIG = 1e12


def _spin(value, decimals=6, minimum=-BIG, suffix=""):
    spin = QDoubleSpinBox()
    spin.setRange(minimum, BIG)
    spin.setDecimals(decimals)
    spin.setValue(float(value))
    spin.setSuffix(suffix)
    return spin


class StepDialog(QDialog):
    """Edits one step. ``state`` is the step to edit, or ``kind`` a new one of that kind."""

    def __init__(self, parent, readable, settable, state=None, kind=None):
        super().__init__(parent)
        self._state = copy.deepcopy(state) if state else queue_steps.new_step(kind)
        step = self._state[queue_steps.STEP_KEY]
        self.kind = step["kind"]
        self.setWindowTitle(queue_steps.KINDS[self.kind])
        form = QFormLayout()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.fields = {}
        if self.kind in queue_steps.NEEDS_PARAMETER:
            combo = QComboBox()
            combo.addItems(settable if self.kind == "set" else readable)
            combo.setCurrentText(step.get("parameter", ""))
            form.addRow("Parameter:", combo)
            self.fields["parameter"] = combo
        if self.kind == "wait":
            self._add(form, "seconds", "Time:", _spin(step["seconds"], 1, 0, " s"))
        if self.kind in ("wait_below", "wait_above", "set"):
            self._add(form, "value", "Value:", _spin(step["value"]))
        if self.kind == "wait_stable":
            target = QCheckBox("Around a target value")
            target.setChecked(bool(step.get("use_target")))
            form.addRow(target)
            self.fields["use_target"] = target
            value = self._add(form, "value", "Target:", _spin(step["value"]))
            value.setEnabled(target.isChecked())
            target.toggled.connect(value.setEnabled)
            self._add(form, "tol", "Tolerance (+-):", _spin(step["tol"], minimum=0))
            self._add(form, "dwell", "Stay within it for:", _spin(step["dwell"], 1, 0, " s"))
        if self.kind in ("wait_below", "wait_above", "wait_stable"):
            timeout = self._add(form, "timeout", "Give up after (0: never):", _spin(step["timeout"], 0, 0, " s"))
            timeout.setToolTip("When it is not reached in time the item fails (and the queue stops, if it is set to).")
        if self.kind == "repeat_until":
            edit = QLineEdit(step.get("expression", ""))
            edit.setPlaceholderText("e.g.  T() > 10   or   abs(Vg()) >= 1")
            edit.setToolTip("A Python expression of the experiment parameters (T() reads one). While it is false, the "
                            "measurement before this step is queued again, with this step.")
            form.addRow("Until:", edit)
            self.fields["expression"] = edit
            maximum = QSpinBox()
            maximum.setRange(1, 100000)
            maximum.setValue(int(step.get("max_repeats", 10)))
            form.addRow("At most:", maximum)
            maximum.setSuffix(" repeats")
            self.fields["max_repeats"] = maximum
            layout.addWidget(QLabel("Put it right after the measurement to repeat."))
        self.error = QLabel("")
        self.error.setStyleSheet("color: #c00;")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add(self, form, key, label, widget):
        form.addRow(label, widget)
        self.fields[key] = widget
        return widget

    def state(self):
        step = self._state[queue_steps.STEP_KEY]
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                step[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                step[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                step[key] = widget.text().strip()
            elif isinstance(widget, QSpinBox):
                step[key] = widget.value()
            else:
                step[key] = widget.value()
        return self._state

    def _ok(self):
        found = queue_steps.problems(self.state())
        if found:
            self.error.setText("Cannot use this step: " + " and ".join(found) + ".")
            return
        self.accept()


class SeriesDialog(QDialog):
    """A measurement repeated for several values of a parameter: for each value the queue sets the parameter, optionally
    waits until it is stable there, and runs the selected measurements."""

    def __init__(self, parent, settable, count):
        super().__init__(parent)
        self.setWindowTitle("Series over a parameter")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"For each value: set the parameter, then run the {count} selected measurement(s). "
                                "The items are put in the queue, where they can be edited."))
        form = QFormLayout()
        layout.addLayout(form)
        self.parameter = QComboBox()
        self.parameter.addItems(settable)
        form.addRow("Parameter:", self.parameter)
        self.start, self.stop = _spin(0), _spin(1)
        form.addRow("From:", self.start)
        form.addRow("To:", self.stop)
        self.points = QSpinBox()
        self.points.setRange(1, 10000)
        self.points.setValue(5)
        form.addRow("Number of values:", self.points)
        self.wait_check = QCheckBox("Wait until it is stable at each value")
        self.wait_check.setChecked(True)
        form.addRow(self.wait_check)
        self.tol, self.dwell, self.timeout = _spin(0.01, minimum=0), _spin(30, 1, 0, " s"), _spin(3600, 0, 0, " s")
        form.addRow("Tolerance (+-):", self.tol)
        form.addRow("Stay within it for:", self.dwell)
        form.addRow("Give up after (0: never):", self.timeout)
        for widget in (self.tol, self.dwell, self.timeout):
            self.wait_check.toggled.connect(widget.setEnabled)
        self.replace = QCheckBox("Replace the selected measurements by the series")
        self.replace.setChecked(True)
        layout.addWidget(self.replace)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def states(self, recipes):
        """The queue states of the series for the recipes ``states`` (a list), in order."""
        name = self.parameter.currentText()
        out = []
        for value in np.linspace(self.start.value(), self.stop.value(), self.points.value()):
            out.append(queue_steps.new_step("set", parameter=name, value=float(value)))
            if self.wait_check.isChecked():
                out.append(queue_steps.new_step("wait_stable", parameter=name, use_target=True, value=float(value),
                                                tol=self.tol.value(), dwell=self.dwell.value(),
                                                timeout=self.timeout.value()))
            out.extend(copy.deepcopy(recipe) for recipe in recipes)
        return out
