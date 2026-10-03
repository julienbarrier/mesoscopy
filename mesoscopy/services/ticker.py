"""One 1 Hz tick for every clock of the application (no widgets).

The elapsed and remaining times, the queue's progress bar and the monitor's traces all follow the clock once per second.
Instead of a timer each, they connect to this one tick, and a subscriber that has a widget is only called while the widget is
shown (or, with ``hidden_every``, once every that many seconds while it is hidden).
"""
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

TICK_MS = 1000


class Ticker(QObject):
    tick = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.start(TICK_MS)

    @property
    def count(self):
        """Seconds counted so far."""
        return self._count

    def _on_timeout(self):
        self._count += 1
        self.tick.emit()

    def connect_visible(self, widget, slot, hidden_every=0):
        """Call ``slot`` on every tick while ``widget`` is shown; while it is hidden never (``hidden_every`` = 0) or once
        every ``hidden_every`` ticks."""
        def on_tick():
            if widget.isVisible() or (hidden_every and self._count % hidden_every == 0):
                slot()

        self.tick.connect(on_tick)
        return on_tick

    def stop(self):
        self._timer.stop()
