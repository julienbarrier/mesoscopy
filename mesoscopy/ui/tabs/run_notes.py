"""Widgets of the run menu: the line of coloured dots (tag) and the dialog for the notes."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from mesoscopy.core.run_tags import TAGS
from mesoscopy.ui.tabs.run_table import DOT_SIZE, TAG_COLORS, dot_pixmap


class TagPicker(QWidget):
    """The tag line of the run menu: the six coloured dots on one line, each selectable, with no frame or label. The
    dot of the tag the run has is outlined. ``tagChosen`` carries the name of the colour, which is what is stored."""

    tagChosen = pyqtSignal(str)

    def __init__(self, current=""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(2)
        self.dots = {}
        for tag in TAGS:
            button = QToolButton()
            button.setIcon(QIcon(dot_pixmap(TAG_COLORS[tag], DOT_SIZE, selected=(tag == current))))
            button.setIconSize(QSize(DOT_SIZE, DOT_SIZE))
            button.setFixedSize(DOT_SIZE + 6, DOT_SIZE + 6)
            button.setStyleSheet("QToolButton { border: none; background: transparent; }")  # no square around the dot
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{tag}" + (" (click again to remove the tag)" if tag == current else ""))
            button.clicked.connect(lambda _=False, t=tag: self.tagChosen.emit(t))
            layout.addWidget(button)
            self.dots[tag] = button
        layout.addStretch()


class NotesDialog(QDialog):
    """A text field for the notes of a run, to enter or edit."""

    def __init__(self, parent, title, notes=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 300)
        layout = QVBoxLayout(self)
        self.edit = QPlainTextEdit(notes)
        self.edit.setPlaceholderText("Notes on this run")
        layout.addWidget(self.edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def notes(self):
        return self.edit.toPlainText().strip()
