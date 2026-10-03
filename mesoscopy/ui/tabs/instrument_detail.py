"""Panel right of the connected instruments: command log, raw commands and readable snapshot of one instrument."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qcodes.instrument import VisaInstrument

from mesoscopy.core.command_log import CommandLog, format_entry
from mesoscopy.core.snapshot_text import rows_to_text, snapshot_rows
from mesoscopy.core.gateway import USER
from mesoscopy.ui.tabs.ui_helpers import pause_when_hidden, set_groupbox_title_bold

PAGE_LOG, PAGE_RAW, PAGE_SNAPSHOT = range(3)
LOG_REFRESH_MS = 500
MAX_LOG_LINES = 1000


def _monospace(widget):
    widget.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    return widget


class InstrumentDetailPanel(QWidget):
    """One of three boxes at a time, for the single instrument selected in the connected list; hidden when
    no instrument is selected. Buttons under the box switch between them."""

    def __init__(self, services):
        super().__init__()
        self.services = services
        self.name = None
        self._log = CommandLog.install()
        self._log_version = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_log_page())
        self.stack.addWidget(self._build_raw_page())
        self.stack.addWidget(self._build_snapshot_page())
        layout.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.page_buttons = QButtonGroup(self)
        self.page_buttons.setExclusive(True)
        for page, text in ((PAGE_LOG, "Command log"), (PAGE_RAW, "Raw command"), (PAGE_SNAPSHOT, "Snapshot")):
            button = QPushButton(text)
            button.setCheckable(True)
            self.page_buttons.addButton(button, page)
            buttons.addWidget(button)
        self.page_buttons.button(PAGE_LOG).setChecked(True)
        self.page_buttons.idClicked.connect(self._show_page)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_log)
        self._pacer = pause_when_hidden(self, self._timer, self._refresh_log)  # the log is only refreshed while it can be seen
        self.setVisible(False)

    # ================= pages =================
    def _build_log_page(self):
        box = QGroupBox("Command log")
        set_groupbox_title_bold(box)
        layout = QVBoxLayout(box)
        self.log_hint = QLabel("")
        self.log_hint.setWordWrap(True)
        self.log_hint.setStyleSheet("color: gray; font-size: 0.9em;")
        layout.addWidget(self.log_hint)
        self.log_view = _monospace(QPlainTextEdit())
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        layout.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_log)
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        row.addWidget(clear)
        row.addWidget(copy)
        row.addStretch()
        layout.addLayout(row)
        return box

    def _build_raw_page(self):
        box = QGroupBox("Raw command")
        set_groupbox_title_bold(box)
        layout = QVBoxLayout(box)
        self.raw_hint = QLabel("")
        self.raw_hint.setWordWrap(True)
        layout.addWidget(self.raw_hint)
        row = QHBoxLayout()
        self.raw_input = _monospace(QLineEdit())
        self.raw_input.setPlaceholderText("Command, e.g. *IDN?")
        self.raw_input.returnPressed.connect(self._send_default)
        self.ask_button = QPushButton("Ask")
        self.ask_button.setToolTip("Send the command and read the answer")
        self.ask_button.clicked.connect(lambda: self._send(ask=True))
        self.write_button = QPushButton("Write")
        self.write_button.setToolTip("Send the command without reading an answer")
        self.write_button.clicked.connect(lambda: self._send(ask=False))
        row.addWidget(self.raw_input, 1)
        row.addWidget(self.ask_button)
        row.addWidget(self.write_button)
        layout.addLayout(row)
        for widget in (self.raw_input, self.ask_button, self.write_button):
            self.services.measuring.gate(widget)  # refused while a measurement runs
        self.raw_output = _monospace(QPlainTextEdit())
        self.raw_output.setReadOnly(True)
        self.raw_output.setPlaceholderText("Commands and answers appear here. Enter asks when the command ends "
                                           "with '?', and writes otherwise.")
        layout.addWidget(self.raw_output, 1)
        return box

    def _build_snapshot_page(self):
        box = QGroupBox("Snapshot")
        set_groupbox_title_bold(box)
        layout = QVBoxLayout(box)
        self.snapshot_tree = QTreeWidget()
        self.snapshot_tree.setColumnCount(4)
        self.snapshot_tree.setHeaderLabels(("Name", "Value", "Unit", "Updated"))
        self.snapshot_tree.setUniformRowHeights(True)
        self.snapshot_tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.snapshot_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.snapshot_tree, 1)
        self.snapshot_message = QLabel("")
        self.snapshot_message.setStyleSheet("color: #c00;")
        layout.addWidget(self.snapshot_message)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Show the values QCoDeS holds now (the instrument is not read: use "
                           "\"Update snapshot\" in the instrument's right-click menu for that)")
        refresh.clicked.connect(self._refresh_snapshot)
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(self._copy_snapshot)
        row.addWidget(refresh)
        row.addWidget(copy)
        row.addStretch()
        layout.addLayout(row)
        self._snapshot_text = ""
        return box

    # ================= selection =================
    def set_selection(self, names):
        """Follow the connected list: shown for exactly one selected instrument, hidden otherwise."""
        self.name = names[0] if len(names) == 1 else None
        self.setVisible(self.name is not None)
        self._log_version = None
        self.raw_output.clear()
        if self.name is not None:
            self._show_page(self.stack.currentIndex())
        else:
            self._pacer.stop()

    def _instrument(self):
        return self.services.station.instruments().get(self.name) if self.name else None

    def _show_page(self, page):
        self.stack.setCurrentIndex(page)
        self._pacer.stop()
        if page == PAGE_LOG:
            self._log_version = None
            self._refresh_log()
            self._pacer.start(LOG_REFRESH_MS)
        elif page == PAGE_RAW:
            self._update_raw_page()
        else:
            self._refresh_snapshot()

    # ================= command log =================
    def _refresh_log(self):
        if self.name is None:
            return
        version, entries = self._log.entries(self.name)
        instrument = self._instrument()
        if instrument is not None and not isinstance(instrument, VisaInstrument):
            self.log_hint.setText(f"{self.name} is not a VISA instrument: its driver may not log commands "
                                  "through QCoDeS, so this log can stay empty.")
        else:
            self.log_hint.setText("Commands QCoDeS sent to the instrument and the answers it got (DEBUG level of "
                                  "the QCoDeS logger), most recent last.")
        if version == self._log_version:
            return
        self._log_version = version
        bar = self.log_view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        self.log_view.setPlainText("\n".join(format_entry(e) for e in entries[-MAX_LOG_LINES:]))
        if at_end:
            bar.setValue(bar.maximum())

    def _clear_log(self):
        if self.name is not None:
            self._log.clear(self.name)
            self._refresh_log()

    # ================= raw commands =================
    def _update_raw_page(self):
        instrument = self._instrument()
        usable = isinstance(instrument, VisaInstrument)
        for widget in (self.raw_input, self.ask_button, self.write_button):
            widget.setEnabled(usable)
        if usable:
            self.raw_hint.setText("Commands go straight to the instrument: validators, limits and ramp rates "
                                  "of the parameters do not apply. Refused while a measurement runs.")
            self.raw_hint.setStyleSheet("color: #a60;")
        else:
            self.raw_hint.setText("Raw commands are only available for VISA instruments.")
            self.raw_hint.setStyleSheet("")

    def _send_default(self):
        self._send(ask=self.raw_input.text().strip().endswith("?"))

    def _send(self, ask):
        instrument, command = self._instrument(), self.raw_input.text().strip()
        status = self.services.status
        if not command or not isinstance(instrument, VisaInstrument):
            return
        name = self.name
        job = self.services.gateway.submit(
            instrument.ask if ask else instrument.write, command, kind=USER, instruments={name},
            label=f"Raw command to {name}",
        )
        if job is None:  # a measurement or another action has the instrument
            status.show(self.services.gateway.last_refusal, 5000)
            return
        self.raw_output.appendPlainText(f"> {command}")
        for widget in (self.ask_button, self.write_button):
            widget.setEnabled(False)  # one command at a time: an ask can wait for the instrument's timeout
        job.signals.result.connect(lambda answer: self._sent(name, ask, answer, None))
        job.signals.error.connect(lambda error: self._sent(name, ask, None, error[1]))

    def _sent(self, name, ask, answer, error):
        if name == self.name:  # the selection may have moved on
            if error is not None:
                self.raw_output.appendPlainText(f"! {type(error).__name__}: {error}")
            elif ask:
                self.raw_output.appendPlainText(f"< {answer}")
            else:
                self.raw_output.appendPlainText("(written)")
            self._update_raw_page()

    # ================= readable snapshot =================
    def _refresh_snapshot(self):
        tree = self.snapshot_tree
        tree.clear()
        self.snapshot_message.setText("")
        self._snapshot_text = ""
        instrument = self._instrument()
        if instrument is None:
            return
        try:
            snapshot = instrument.snapshot(update="Never")  # what QCoDeS holds: the instrument is not read
        except Exception as e:
            self.snapshot_message.setText(f"Cannot take the snapshot: {type(e).__name__}: {e}")
            return
        rows = snapshot_rows(snapshot, self.name)
        self._snapshot_text = rows_to_text(rows)
        stack = []  # (depth, item) of the groups above the current row
        for row in rows:
            while stack and stack[-1][0] >= row["depth"]:
                stack.pop()
            item = QTreeWidgetItem([row["name"], row["value"], row["unit"], row["updated"]])
            if row["group"]:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            (stack[-1][1].addChild if stack else tree.addTopLevelItem)(item)
            if row["group"]:
                stack.append((row["depth"], item))
        tree.expandToDepth(0)
        for column in range(3):
            tree.resizeColumnToContents(column)
        if not rows:
            self.snapshot_message.setText("Nothing to show: the instrument has no parameters in its snapshot.")

    def _copy_snapshot(self):
        if self._snapshot_text:
            QApplication.clipboard().setText(self._snapshot_text)
            self.services.status.show("Snapshot copied to the clipboard.", 3000)

    def shutdown(self):
        self._pacer.stop()
