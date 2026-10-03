"""Pop-up to pick a run of the selected database: experiment, then run (the Data tab's explorer, in a dialog)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from mesoscopy.ui.tabs.run_table import fill_run_row, setup_run_table
from mesoscopy.core.db_explorer import RUN_COLUMNS, describe_error, list_experiments, list_runs


class RunPickerDialog(QDialog):
    """Select an experiment and a run of the database selected in the Data tab (there is one database in use, this
    dialog does not browse others). ``selection()`` gives (database path, run id) once it was accepted."""

    def __init__(self, parent, db_path, title="Select a run"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self._db_path = db_path
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        form.addRow("Database:", QLabel(os.path.basename(db_path)))
        self.experiment_combo = QComboBox()
        self.experiment_combo.setPlaceholderText("Select an experiment")
        self.experiment_combo.currentIndexChanged.connect(self._refresh_runs)
        form.addRow("Experiment:", self.experiment_combo)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.message)

        self.runs_table = QTableWidget(0, len(RUN_COLUMNS))
        self.runs_table.setHorizontalHeaderLabels(RUN_COLUMNS)
        self.runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        setup_run_table(self.runs_table)  # the tag dot and the note preview in the name cell
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.runs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.runs_table.verticalHeader().setVisible(False)
        header = self.runs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.runs_table.itemSelectionChanged.connect(self._update_ok)
        self.runs_table.itemDoubleClicked.connect(lambda _item: self.accept() if self._ok.isEnabled() else None)
        layout.addWidget(self.runs_table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fill_experiments()

    def _show(self, text):
        self.message.setText(text)
        self.message.setStyleSheet("color: #c00;" if text.startswith("Cannot") else "")
        self.message.setVisible(bool(text))

    def _fill_experiments(self):
        self._show("")
        try:
            experiments = list_experiments(self._db_path)
        except Exception as e:
            self._show(f"Cannot read database ({describe_error(e)}).")
            return
        if not experiments:
            self._show("This database contains no experiments.")
            return
        self.experiment_combo.blockSignals(True)
        for exp in experiments:
            sample = f", sample: {exp['sample_name']}" if exp["sample_name"] else ""
            self.experiment_combo.addItem(f"{exp['name']}{sample} ({exp['n_runs']} runs)", exp["exp_id"])
        self.experiment_combo.setCurrentIndex(-1)
        self.experiment_combo.blockSignals(False)

    def _refresh_runs(self):
        self.runs_table.setRowCount(0)
        exp_id = self.experiment_combo.currentData()
        if exp_id is None:
            return
        try:
            runs = list_runs(self._db_path, exp_id)
        except Exception as e:
            self._show(f"Cannot read runs: {describe_error(e)}")
            return
        self._show("" if runs else "This experiment has no runs.")
        self.runs_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            fill_run_row(self.runs_table, row, run)

    def _selected_run(self):
        rows = self.runs_table.selectionModel().selectedRows()
        return self.runs_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def _update_ok(self):
        self._ok.setEnabled(self._selected_run() is not None)

    def selection(self):
        """(database path, run id) of the selected run."""
        return self._db_path, self._selected_run()
