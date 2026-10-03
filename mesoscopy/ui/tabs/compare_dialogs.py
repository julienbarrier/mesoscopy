"""Comparing the snapshots of two runs: a dialog to pick the second run, and the one that shows the differences."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from mesoscopy.ui.tabs.run_table import fill_run_row, setup_run_table
from mesoscopy.core.db_explorer import RUN_COLUMNS, describe_error, list_db_files, list_experiments, list_runs
from mesoscopy.core.snapshot_diff import describe_runs, diff_to_text
from mesoscopy.ui.tabs.ui_helpers import make_text_selectable, set_groupbox_title_bold


class ComparePickerDialog(QDialog):
    """A stripped Data tab to pick the run to compare with: the database folder and file on the left, the experiment
    explorer on the right. "Get diff" accepts the dialog; ``selection()`` is then (database path, run id).

    It only reads databases: it does not change the database selected in the Data tab, which stays the one in use."""

    def __init__(self, parent, folder="", db_name=""):
        super().__init__(parent)
        self.setWindowTitle("Compare with another run")
        self.resize(1000, 520)
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        layout.addLayout(body, 1)

        # left: the database
        database = QGroupBox("Database")
        set_groupbox_title_bold(database)
        left = QVBoxLayout(database)
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Database folder")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        left.addWidget(QLabel("Database folder:"))
        left.addLayout(row)
        left.addWidget(QLabel("Database file:"))
        self.db_combo = QComboBox()
        self.db_combo.currentIndexChanged.connect(self._refresh_experiments)
        left.addWidget(self.db_combo)
        left.addStretch()
        body.addWidget(database, 1)

        # right: the experiment explorer
        explorer = QGroupBox("Experiment Explorer")
        set_groupbox_title_bold(explorer)
        right = QVBoxLayout(explorer)
        self.experiment_combo = QComboBox()
        self.experiment_combo.setPlaceholderText("Select an experiment")
        self.experiment_combo.currentIndexChanged.connect(self._refresh_runs)
        right.addWidget(self.experiment_combo)
        self.message = make_text_selectable(QLabel(""))
        self.message.setWordWrap(True)
        right.addWidget(self.message)
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
        self.runs_table.itemSelectionChanged.connect(self._update_button)
        self.runs_table.itemDoubleClicked.connect(lambda _item: self.accept() if self.diff_button.isEnabled() else None)
        right.addWidget(self.runs_table, 1)
        body.addWidget(explorer, 2)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.diff_button = QPushButton("Get diff")
        self.diff_button.setEnabled(False)
        self.diff_button.setDefault(True)
        self.diff_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.diff_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._fill_files(db_name)

    # ----- the database -----
    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select the database folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._fill_files()

    def _fill_files(self, preferred=""):
        self.db_combo.blockSignals(True)
        self.db_combo.clear()
        self.db_combo.addItems(list_db_files(self.folder_edit.text()))
        if preferred:
            self.db_combo.setCurrentText(preferred)
        self.db_combo.blockSignals(False)
        self._refresh_experiments()

    def _db_path(self):
        name = self.db_combo.currentText()
        return os.path.join(self.folder_edit.text(), name) if name else None

    def _show(self, text):
        self.message.setText(text)
        self.message.setStyleSheet("color: #c00;" if text.startswith("Cannot") else "")
        self.message.setVisible(bool(text))

    # ----- the experiments and runs -----
    def _refresh_experiments(self):
        self.experiment_combo.blockSignals(True)
        self.experiment_combo.clear()
        self.experiment_combo.blockSignals(False)
        self.runs_table.setRowCount(0)
        self._show("" if self._db_path() else "Select a database folder that contains .db files.")
        if self._db_path() is None:
            return
        try:
            experiments = list_experiments(self._db_path())
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
        if exp_id is None or self._db_path() is None:
            return
        try:
            runs = list_runs(self._db_path(), exp_id)
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

    def _update_button(self):
        self.diff_button.setEnabled(self._selected_run() is not None)

    def selection(self):
        """(database path, run id) of the selected run."""
        return self._db_path(), self._selected_run()


class SnapshotDiffDialog(QDialog):
    """The runs compared, and the parameters that differ between their snapshots (name, value in run A, value in
    run B) in the style of the instrument snapshot. What is identical is not shown. The text can be copied."""

    def __init__(self, parent, run_a, run_b, rows):
        super().__init__(parent)
        self.setWindowTitle("Snapshot differences")
        self.resize(900, 600)
        self._header = describe_runs(run_a, run_b)
        self._rows = rows
        layout = QVBoxLayout(self)
        self.header_label = make_text_selectable(QLabel("\n".join(self._header)))
        self.header_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.header_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(("Name", "Run A", "Run B"))
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.tree, 1)
        self._fill_tree()

        self.summary = QLabel("")
        layout.addWidget(self.summary)
        buttons = QHBoxLayout()
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(self.copy_to_clipboard)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        count = sum(1 for r in rows if not r["group"])
        self.summary.setText(f"{count} difference(s)." if count else "No difference between the two snapshots.")

    def _fill_tree(self):
        stack = []  # (depth, item) of the groups above the current row
        for row in self._rows:
            while stack and stack[-1][0] >= row["depth"]:
                stack.pop()
            item = QTreeWidgetItem([row["name"], row["a"], row["b"]])
            if row["group"]:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            (stack[-1][1].addChild if stack else self.tree.addTopLevelItem)(item)
            if row["group"]:
                stack.append((row["depth"], item))
        self.tree.expandAll()
        for column in range(2):
            self.tree.resizeColumnToContents(column)

    def text(self):
        return diff_to_text(self._header, self._rows)

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.text())
