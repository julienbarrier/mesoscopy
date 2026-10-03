"""The signals of an instrument job (see ``core/gateway``)."""
from PyQt6.QtCore import QObject, pyqtSignal


class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)


