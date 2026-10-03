"""Alarms on parameters (no widgets).

A parameter with an alarm is watched wherever the application reads it: at every point of a measurement, at every reading
of the Monitor tab (which also reads the alarmed parameters that are not monitored) and after a read or a set in the
Parameter explorer. When a value reaches the limit (``core/alarms``) the alarm is raised once, until the value has come
back inside. A raised alarm is logged as a WARNING (when the QCoDeS logging is running), kept in the history of the
session, shown in the status bar, and the action chosen in the Settings is taken: only the message, pause the
measurement, stop it, or stop it and ramp to 0.
"""
import logging
import threading
import time
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal

from mesoscopy.core import alarms as limits_of
from mesoscopy.core.parameter_io import get_children, source_chain_ids
from mesoscopy.services.run_controller import RUNNING

LOG = logging.getLogger("mesoscopy.alarms")
ACTIONS = ("message", "pause", "stop", "stop_ramp")
ACTION_TEXT = {"message": "message only", "pause": "measurement paused", "stop": "measurement stopped",
               "stop_ramp": "measurement stopped, ramping to 0"}
HISTORY_MAX = 1000
RUN_READ_PERIOD_S = 1.0  # the alarmed parameters a measurement does not read are read at most this often


def _walk(node, found):
    for child in get_children(node).values():
        if hasattr(child, "get_latest"):
            found[child.full_name] = child
        else:
            _walk(child, found)


def all_parameters(station, registry):
    """{full name: parameter} of everything an alarm can watch: the instrument parameters and the experiment ones."""
    found = {}
    if station is not None:
        for name, component in station.components.items():
            if hasattr(component, "submodules"):
                _walk(component, found)
    found.update(registry.parameters())
    return found


class AlarmService(QObject):
    """The alarms of the session. ``changed`` when the set of alarmed parameters changes, ``alarmRaised(record)`` when
    one goes off (from any thread), ``historyChanged`` when the history does."""

    changed = pyqtSignal()
    alarmRaised = pyqtSignal(object)
    historyChanged = pyqtSignal()

    def __init__(self, services):
        super().__init__()
        self.services = services
        self._names = {}          # full name -> parameter (None while it is not available)
        self._armed = {}          # (full name, side) -> True once raised, until the value is back inside
        self._last_read = 0.0
        self._lock = threading.Lock()
        self.history = deque(maxlen=HISTORY_MAX)
        self.alarmRaised.connect(self._take_action)

    # ================= the set of alarms =================
    def parameters(self):
        return [p for p in self._names.values() if p is not None]

    def names(self):
        """Full names of the alarmed parameters (what a session remembers)."""
        return list(self._names)

    def has(self, parameter):
        return parameter.full_name in self._names

    def by_id(self, key):
        return next((p for p in self.parameters() if id(p) == key), None)

    def add(self, parameter):
        """Put an alarm on ``parameter``. Returns (True, message) or (False, why not)."""
        if self.has(parameter):
            return False, f"{parameter.full_name} has an alarm already."
        if not limits_of.has_limits(parameter):
            return False, (f"{parameter.full_name} has no limits to raise an alarm from: give it safe limits "
                           "(Edit... for an experiment parameter).")
        self._names[parameter.full_name] = parameter
        self.changed.emit()
        return True, f"Alarm on {parameter.full_name}: {self.describe(parameter)}."

    def remove(self, parameter):
        if self._names.pop(parameter.full_name, "absent") != "absent":
            self._armed = {k: v for k, v in self._armed.items() if k[0] != parameter.full_name}
            self.changed.emit()

    def restore_names(self, names):
        """Set the alarms from a session: they are attached to their parameters as soon as these are available."""
        self._names = {str(n): None for n in names or []}
        self._armed = {}
        self.sync()

    def sync(self):
        """Attach the alarms to the parameters now available (an instrument that was reloaded has new objects)."""
        if not self._names:
            return
        found = all_parameters(self.services.station.station, self.services.registry)
        for name in self._names:
            self._names[name] = found.get(name)
        self.changed.emit()

    # ================= the limits =================
    @property
    def percent(self):
        return self.services.settings.alarm_percent

    def thresholds(self, parameter):
        return limits_of.thresholds(parameter, self.percent)

    def describe(self, parameter):
        """The limits of an alarm in words: '>= 1.8 V or <= -1.8 V' (the sides that are watched)."""
        low, high = self.thresholds(parameter)
        unit = f" {parameter.unit}" if getattr(parameter, "unit", "") else ""
        parts = ([f">= {high:g}{unit}"] if high is not None else []) + ([f"<= {low:g}{unit}"] if low is not None else [])
        return f"{self.percent:g} % of the allowed values ({' or '.join(parts)})"

    # ================= checking =================
    def check_values(self, pairs):
        """Check readings: ``pairs`` = [(parameter, value)] (from any thread). Values that are not numbers are skipped."""
        for parameter, value in pairs:
            if parameter.full_name in self._names:
                self._check(parameter, value)

    def check_run(self, fresh):
        """Called after every point of a measurement (in the measurement thread); returns the alarms that went off, so
        that the measurement can pause or stop at once. ``fresh``: parameters whose cached
        value is current (the swept and measured ones, and what they come from): their last value is used, the other
        alarmed parameters are read, at most once per second."""
        raised = []
        parameters = self.parameters()
        if not parameters:
            return raised
        fresh_ids = source_chain_ids(fresh)
        read_now = time.monotonic() - self._last_read >= RUN_READ_PERIOD_S
        for parameter in parameters:
            try:
                if id(parameter) in fresh_ids:
                    value = parameter.get_latest()
                elif read_now:
                    value = parameter.get()
                else:
                    continue
            except Exception:
                continue  # an alarm never stops a measurement because a reading failed (a breakout condition does)
            record = self._check(parameter, value)
            if record is not None:
                raised.append(record)
        if read_now:
            self._last_read = time.monotonic()
        return raised

    def _check(self, parameter, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if value != value:  # NaN
            return
        limits = self.thresholds(parameter)
        side = limits_of.side_of(value, limits)
        with self._lock:
            for watched in (limits_of.HIGH, limits_of.LOW):
                key = (parameter.full_name, watched)
                if self._armed.get(key) and limits_of.rearmed(value, watched, limits):
                    self._armed[key] = False
            if side is None or self._armed.get((parameter.full_name, side)):
                return None
            self._armed[(parameter.full_name, side)] = True
        return self._raise(parameter, value, side, limits[1] if side == limits_of.HIGH else limits[0])

    def _raise(self, parameter, value, side, threshold):
        action = self.services.settings.alarm_action
        unit = f" {parameter.unit}" if getattr(parameter, "unit", "") else ""
        record = {
            "time": time.time(), "name": parameter.full_name, "value": value, "unit": getattr(parameter, "unit", ""),
            "side": side, "threshold": threshold, "action": action,
            "limit": limits_of.describe_limit(parameter, side, self.percent, threshold),
            "text": f"ALARM {parameter.full_name} = {value:.4g}{unit} (limit {threshold:g}{unit}, "
                    f"{limits_of.describe_limit(parameter, side, self.percent, threshold)})",
        }
        if logging.getLogger().handlers:  # only when the QCoDeS logging is running
            LOG.warning(record["text"])
        with self._lock:
            self.history.append(record)
        self.alarmRaised.emit(record)
        self.historyChanged.emit()
        return record

    # ================= what an alarm does =================
    def _take_action(self, record):
        """(GUI thread) the action chosen in the Settings, for a measurement that is going on."""
        run = self.services.run
        action = record["action"]
        if action == "pause" and run.state == RUNNING:
            run.toggle_pause()
        elif action == "stop" and run.running:
            run.stop()
        elif action == "stop_ramp" and run.running:
            run.stop_and_ramp_to_zero()

    def clear_history(self):
        """Clear what the Monitor tab shows (the log file keeps its warnings)."""
        with self._lock:
            self.history.clear()
        self.historyChanged.emit()
