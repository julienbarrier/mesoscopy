"""Log explorer pop-up: the QCoDeS logs of the log folder, filterable by instrument, level and text."""
import os

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QTimer, Qt
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTableView, QVBoxLayout,
)

from mesoscopy.core.log_reader import (
    LEVELS, filter_records, find_log_files, read_log, root_instruments,
)

COLUMNS = ("Time", "Level", "Instrument", "Logger", "Message")
LEVEL_FILTERS = (("All levels", 0), ("Info and above", LEVELS["INFO"]), ("Warnings and above", LEVELS["WARNING"]),
                 ("Errors only", LEVELS["ERROR"]))
COLORS = {"WARNING": QColor("#b36b00"), "ERROR": QColor("#c00000"), "CRITICAL": QColor("#c00000")}
FOLLOW_MS = 2000


class _RecordsModel(QAbstractTableModel):
    """The records shown: a plain list, so that tens of thousands of lines stay fast."""

    def __init__(self):
        super().__init__()
        self.records = []

    def set_records(self, records):
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        record = self.records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (record.time, record.level, record.instrument, record.logger, record.first_line())[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and record.level in COLORS:
            return COLORS[record.level]
        return None


class LogViewerDialog(QDialog):
    """Shows the QCoDeS log files found in the log folder (and only there). Filters: instrument (a channel counts
    for its instrument), minimum level (errors included) and a text. Selecting a record shows all of it,
    traceback included."""

    def __init__(self, parent, folder, instruments=()):
        super().__init__(parent)
        self.setWindowTitle(f"QCoDeS logs: {folder}")
        self.resize(1100, 650)
        self._folder = folder
        self._known = list(instruments)
        self._records = []
        self._signature = None  # (path, size) of what is shown, to reload only when the file grew

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(280)
        self.file_combo.currentIndexChanged.connect(self.reload)
        top.addWidget(QLabel("Log file:"))
        top.addWidget(self.file_combo, 1)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(lambda: self.reload(force=True))
        top.addWidget(reload_button)
        self.follow_check = QCheckBox("Follow")
        self.follow_check.setToolTip("Reload every 2 s while the file grows")
        self.follow_check.toggled.connect(self._follow_toggled)
        top.addWidget(self.follow_check)
        layout.addLayout(top)

        filters = QHBoxLayout()
        self.instrument_combo = QComboBox()
        self.instrument_combo.setMinimumWidth(160)
        self.instrument_combo.currentIndexChanged.connect(self.apply_filters)
        self.level_combo = QComboBox()
        for label, _ in LEVEL_FILTERS:
            self.level_combo.addItem(label)
        self.level_combo.currentIndexChanged.connect(self.apply_filters)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search the messages and logger names")
        self.search_edit.textChanged.connect(self.apply_filters)
        filters.addWidget(QLabel("Instrument:"))
        filters.addWidget(self.instrument_combo)
        filters.addWidget(QLabel("Level:"))
        filters.addWidget(self.level_combo)
        filters.addWidget(self.search_edit, 1)
        layout.addLayout(filters)

        self.model = _RecordsModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((170, 70, 130, 200)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().selectionChanged.connect(self._show_detail)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.detail.setPlaceholderText("Select a record to see all of it, a traceback included.")
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.summary = QLabel("")
        bottom.addWidget(self.summary, 1)
        copy = QPushButton("Copy shown records")
        copy.clicked.connect(self._copy)
        bottom.addWidget(copy)
        layout.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.reload(force=False))
        self.refresh_files()

    # ----- files -----
    def refresh_files(self):
        """List the log files of the folder, newest first, and show the newest."""
        files = find_log_files(self._folder)
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for path in files:
            self.file_combo.addItem(os.path.basename(path), path)
        self.file_combo.blockSignals(False)
        if not files:
            self._records = []
            self.model.set_records([])
            self.summary.setText(f"No QCoDeS log file in {self._folder}. Press \"Start logging\" first: "
                                 "the log is then written to this folder.")
            return
        self.reload(force=True)

    def reload(self, *_args, force=True):
        path = self.file_combo.currentData()
        if path is None:
            return
        try:
            signature = (path, os.path.getsize(path))
            if not force and signature == self._signature:
                return
            records, truncated = read_log(path)
        except OSError as e:
            self.summary.setText(f"Cannot read {os.path.basename(path)}: {e}")
            return
        self._signature = signature
        self._records = records
        self._truncated = truncated
        current = self.instrument_combo.currentData()
        self.instrument_combo.blockSignals(True)
        self.instrument_combo.clear()
        self.instrument_combo.addItem("All instruments", "")
        for name in root_instruments(records, self._known):
            self.instrument_combo.addItem(name, name)
        index = self.instrument_combo.findData(current) if current is not None else 0
        self.instrument_combo.setCurrentIndex(max(index, 0))
        self.instrument_combo.blockSignals(False)
        self.apply_filters()

    def _follow_toggled(self, on):
        if on:
            self._timer.start(FOLLOW_MS)
        else:
            self._timer.stop()

    # ----- filters -----
    def apply_filters(self, *_args):
        shown = filter_records(
            self._records, instrument=self.instrument_combo.currentData() or "",
            min_level=LEVEL_FILTERS[self.level_combo.currentIndex()][1], text=self.search_edit.text(),
        )
        bar = self.table.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        self.model.set_records(shown)
        if self.follow_check.isChecked() and at_end:
            self.table.scrollToBottom()
        errors = sum(1 for r in shown if r.severity >= LEVELS["ERROR"])
        note = f" (only the last {20} MB of the file are read)" if getattr(self, "_truncated", False) else ""
        self.summary.setText(f"{len(shown)} of {len(self._records)} records, {errors} error(s){note}")
        self.detail.clear()

    def _show_detail(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail.clear()
            return
        record = self.model.records[rows[0].row()]
        self.detail.setPlainText(f"{record.time}  {record.level}  {record.logger}  "
                                 f"{record.module}.{record.function}:{record.line}\n\n{record.message}")

    def _copy(self):
        QApplication.clipboard().setText("\n".join(r.as_text() for r in self.model.records))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
