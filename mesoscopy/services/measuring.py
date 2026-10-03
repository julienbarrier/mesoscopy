"""Whether a measurement is going on, and the controls that cannot be used meanwhile (greyed out as soon as it starts).

While a measurement runs (or the queue is at work, between two of its items) the instrument gateway refuses everything
else that touches the instruments: reading, setting, ramping, raw commands, loading stations and instruments,
disconnecting. The tabs register those controls here with ``gate``: they are disabled the moment the run starts and
get back the state they would have had otherwise when it is over. The widgets are handled by duck typing: this module
imports none.
"""
import weakref

from PyQt6.QtCore import QObject, pyqtSignal

from mesoscopy.services.run_controller import IDLE

HINT = "Not available while a measurement is running."


class Measuring(QObject):
    """``active`` is True from the click on Run (or the start of the queue) to the end of the last run."""

    changed = pyqtSignal(bool)

    def __init__(self, services):
        super().__init__()
        self.services = services
        self.active = False
        self._gated = []  # (weak reference to the widget, its bookkeeping)
        services.run.runStateChanged.connect(lambda _state: self._update())
        services.queue.stateChanged.connect(lambda _state: self._update())

    def _update(self):
        active = self.services.run.state != IDLE or self.services.queue.active
        if active == self.active:
            return
        self.active = active
        self._gated = [(ref, entry) for ref, entry in self._gated if ref() is not None]
        for ref, entry in self._gated:
            self._apply(ref(), entry)
        self.changed.emit(active)

    def gate(self, widget):
        """Disable ``widget`` while a measurement runs. Whatever else calls ``setEnabled`` on it keeps working: the
        widget is enabled when it is wanted enabled and no measurement runs. Returns the widget."""
        parent = widget.parentWidget()
        entry = {"want": widget.isEnabledTo(parent) if parent is not None else widget.isEnabled(),
                 "original": widget.setEnabled, "hinted": False, "tip": ""}

        def set_enabled(value=True):
            entry["want"] = bool(value)
            self._apply(widget, entry)

        widget.setEnabled = set_enabled
        widget.setDisabled = lambda value=True: set_enabled(not value)
        self._gated = [(ref, e) for ref, e in self._gated if ref() is not None]
        self._gated.append((weakref.ref(widget), entry))
        self._apply(widget, entry)
        return widget

    def _apply(self, widget, entry):
        locked = self.active
        try:
            entry["original"](entry["want"] and not locked)
            if locked and entry["want"] and not entry["hinted"]:
                entry["tip"] = widget.toolTip()
                widget.setToolTip(f"{entry['tip']}\n{HINT}" if entry["tip"] else HINT)
                entry["hinted"] = True
            elif entry["hinted"] and not (locked and entry["want"]):
                widget.setToolTip(entry["tip"])
                entry["hinted"] = False
        except RuntimeError:  # the widget was deleted (a table that was rebuilt)
            pass

    def block(self, action):
        """Disable a menu entry (built when the menu opens) while a measurement runs. Returns the action."""
        if self.active:
            action.setEnabled(False)
            action.setToolTip(HINT)
        return action
