"""Review dialog of "Load Snapshot": what will be changed in the instruments and in the application."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from mesoscopy.core.parameter_io import format_value


def _checkable_item(text):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(Qt.CheckState.Checked)
    return item


def _read_only(text):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class SnapshotDialog(QDialog):
    """Shows the values that will be written to the instruments and the experiment parameters that will be
    created or replaced, each with a checkbox, and asks for confirmation. Nothing has been changed when it opens."""

    def __init__(self, parent, summary, value_changes, definition_changes, setup_available, notes=(),
                 title="Load snapshot", show_setup=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 620)
        self._values = list(value_changes)
        self._definitions = [c for c in definition_changes if c.status != "same"]
        layout = QVBoxLayout(self)

        header = QLabel(summary)
        header.setWordWrap(True)
        layout.addWidget(header)
        for note in notes:
            label = QLabel(note)
            label.setWordWrap(True)
            label.setStyleSheet("color: #a60;")
            layout.addWidget(label)

        # instrument values
        self.values_box = QGroupBox(f"Set {len(self._values)} instrument parameter(s) to their value in the run")
        self.values_box.setCheckable(True)
        self.values_box.setChecked(bool(self._values))
        self.values_box.setEnabled(bool(self._values))
        box = QVBoxLayout(self.values_box)
        warning = QLabel("These values are written to the instruments (sources are ramped within the limits of "
                         "their experiment parameter, if they have one). Untick what must not change, for "
                         "example an output that must stay off.")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #a60;")
        box.addWidget(warning)
        self.values_table = _table(("Parameter", "Now", "In the run"))
        self.values_table.setRowCount(len(self._values))
        for row, change in enumerate(self._values):
            self.values_table.setItem(row, 0, _checkable_item(change.label))
            self.values_table.setItem(row, 1, _read_only("?" if change.current is None else format_value(change.current)))
            self.values_table.setItem(row, 2, _read_only(format_value(change.target)))
        box.addWidget(self.values_table)
        buttons = QHBoxLayout()
        for text, state in (("Select all", Qt.CheckState.Checked), ("Select none", Qt.CheckState.Unchecked)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, s=state: self._set_all(self.values_table, s))
            buttons.addWidget(button)
        buttons.addStretch()
        box.addLayout(buttons)
        if not self._values:
            box.addWidget(QLabel("All instrument values already match the run."))
        layout.addWidget(self.values_box, 3)

        # experiment parameters
        self.definitions_box = QGroupBox(f"Create or replace {len(self._definitions)} experiment parameter(s)")
        self.definitions_box.setCheckable(True)
        self.definitions_box.setChecked(bool(self._definitions))
        self.definitions_box.setEnabled(bool(self._definitions))
        box = QVBoxLayout(self.definitions_box)
        self.definitions_table = _table(("Name", "Status", "Details"))
        self.definitions_table.setRowCount(len(self._definitions))
        for row, change in enumerate(self._definitions):
            self.definitions_table.setItem(row, 0, _checkable_item(change.definition.name))
            self.definitions_table.setItem(row, 1, _read_only(change.status))
            details = change.definition.source_text() if change.status == "new" else change.differences()
            self.definitions_table.setItem(row, 2, _read_only(details))
        box.addWidget(self.definitions_table)
        if not self._definitions:
            box.addWidget(QLabel("The experiment parameters the run needs already exist, unchanged."))
        layout.addWidget(self.definitions_box, 2)

        self.setup_check = QCheckBox("Set up the Measurement tab (names, sweeps, measured parameters). Nothing is run.")
        self.setup_check.setChecked(setup_available)
        self.setup_check.setEnabled(setup_available)
        if not setup_available:
            self.setup_check.setToolTip("This run holds nothing the Measurement tab could be set up from.")
        self.setup_check.setVisible(show_setup)
        layout.addWidget(self.setup_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Load")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _set_all(table, state):
        for row in range(table.rowCount()):
            table.item(row, 0).setCheckState(state)

    def selected_values(self):
        """The value changes to apply (none when the group is unticked)."""
        if not self.values_box.isChecked():
            return []
        for row, change in enumerate(self._values):
            change.checked = self.values_table.item(row, 0).checkState() == Qt.CheckState.Checked
        return [c for c in self._values if c.checked]

    def definition_changes(self):
        """All definition changes, with ``checked`` set from the dialog (unticked group: none is applied)."""
        for row, change in enumerate(self._definitions):
            change.checked = self.definitions_box.isChecked() and \
                self.definitions_table.item(row, 0).checkState() == Qt.CheckState.Checked
        return self._definitions

    def wants_setup(self):
        return self.setup_check.isChecked()
