"""Messages for the status bar, from anywhere in the application (no widgets)."""
from PyQt6.QtCore import QObject, pyqtSignal


class StatusMessages(QObject):
    """Anything that has something to tell the user calls ``show``; the main window puts it in the status bar."""

    message = pyqtSignal(str, int)  # text, time in ms (0: until the next message)

    def show(self, text, timeout_ms=0):
        self.message.emit(text, timeout_ms)
