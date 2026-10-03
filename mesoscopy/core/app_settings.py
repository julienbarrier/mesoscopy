"""The application's settings, remembered between sessions (QtCore only, no widgets).

Stored with QSettings (the native place of each system: a plist on macOS, the registry on Windows, an ini file on
Linux), every value as JSON text so that it comes back with its type. ``MESOSCOPY_SETTINGS_FILE`` points to an ini
file to use instead (tests, a second configuration).

What is kept:
* default folders (station, database, logs), used when the application starts,
* whether to restore the previous session at start and whether to load the last station,
* the last station file,
* how several breakout conditions combine,
* what to do when a measurement fails (ramp the changed experiment parameters to 0) and how often to retry a call
  that fails because an instrument does not answer,
* the memory the live plot may use for the earlier runs it draws faded,
* the sparklines of the status bar (shown or not, how many, over how long),
* the queue as it is now, written at every change, so that a crash or a power cut can be recovered from,
* QCoDeS configuration values chosen in the settings dialog, applied again at each start,
* the session: window layout and the entries of the fields, as one JSON document.
"""
import json
import os

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

ORGANISATION = "mesoscopy"
APPLICATION = "mesoscopy"
FOLDER_KINDS = ("station", "database", "logs")


class AppSettings(QObject):
    """The settings. ``changed`` is emitted by whoever edits them (the Settings window) so that what depends on
    them (the status bar sparklines, the tooltip of the breakout box) can update itself."""

    changed = pyqtSignal()

    def __init__(self, path=None):
        super().__init__()
        path = path or os.environ.get("MESOSCOPY_SETTINGS_FILE")
        self._q = QSettings(path, QSettings.Format.IniFormat) if path else QSettings(ORGANISATION, APPLICATION)

    def notify_changed(self):
        self.changed.emit()

    def file_name(self):
        """Where the settings are stored."""
        return self._q.fileName()

    def _get(self, key, default=None):
        text = self._q.value(key)
        if text is None:
            return default
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return default

    def _set(self, key, value):
        self._q.setValue(key, json.dumps(value))
        self._q.sync()

    # ----- folders -----
    def default_folder(self, kind):
        return self._get(f"folders/{kind}", "") or ""

    def set_default_folder(self, kind, path):
        self._set(f"folders/{kind}", path or "")

    # ----- session -----
    @property
    def restore_session(self):
        return bool(self._get("session/restore", True))

    @restore_session.setter
    def restore_session(self, value):
        self._set("session/restore", bool(value))

    def session(self):
        """The saved session ({} if there is none)."""
        data = self._get("session/data", {})
        return data if isinstance(data, dict) else {}

    def save_session(self, data):
        self._set("session/data", data)

    def clear_session(self):
        self._q.remove("session/data")
        self._q.sync()

    # ----- station -----
    @property
    def load_last_station(self):
        return bool(self._get("station/load_last", False))

    @load_last_station.setter
    def load_last_station(self, value):
        self._set("station/load_last", bool(value))

    @property
    def last_station(self):
        return self._get("station/last", "") or ""

    @last_station.setter
    def last_station(self, path):
        self._set("station/last", path or "")

    def last_instruments(self, station_file):
        """Names of the instruments that were loaded the last time ``station_file`` was used."""
        data = self._get("station/instruments", {})
        names = data.get(os.path.abspath(station_file), []) if isinstance(data, dict) else []
        return [n for n in names if isinstance(n, str)]

    def set_last_instruments(self, station_file, names):
        data = self._get("station/instruments", {})
        data = data if isinstance(data, dict) else {}
        data[os.path.abspath(station_file)] = list(names)
        self._set("station/instruments", data)

    # ----- sparklines in the status bar -----
    @property
    def show_sparklines(self):
        return bool(self._get("sparklines/show", True))

    @show_sparklines.setter
    def show_sparklines(self, value):
        self._set("sparklines/show", bool(value))

    @property
    def sparkline_max(self):
        return int(self._get("sparklines/max", 6))

    @sparkline_max.setter
    def sparkline_max(self, value):
        self._set("sparklines/max", int(value))

    @property
    def sparkline_minutes(self):
        return int(self._get("sparklines/minutes", 10))

    @sparkline_minutes.setter
    def sparkline_minutes(self, value):
        self._set("sparklines/minutes", int(value))

    # ----- measurement -----
    @property
    def breakout_mode(self):
        """"any" (the default): stop when one breakout condition is true; "all": when every one is true at once."""
        mode = self._get("measurement/breakout_mode", "any")
        return mode if mode in ("all", "any") else "any"

    @breakout_mode.setter
    def breakout_mode(self, value):
        self._set("measurement/breakout_mode", "all" if value == "all" else "any")

    @property
    def use_threads(self):
        """What the user chose for dond's ``use_threads``, or None to follow the default."""
        value = self._get("measurement/use_threads", None)
        return None if value is None else bool(value)

    @use_threads.setter
    def use_threads(self, value):
        if value is None:
            self._q.remove("measurement/use_threads")
            self._q.sync()
        else:
            self._set("measurement/use_threads", bool(value))

    @property
    def ramp_on_error(self):
        """After a measurement failed (a driver error), bring the experiment parameters the application changed to 0."""
        return bool(self._get("measurement/ramp_on_error", True))

    @ramp_on_error.setter
    def ramp_on_error(self, value):
        self._set("measurement/ramp_on_error", bool(value))

    @property
    def retry_attempts(self):
        """How many times a measurement retries a read or set that failed because the instrument did not answer
        (0: it fails at once)."""
        try:
            return min(max(int(self._get("measurement/retry_attempts", 3)), 0), 100)
        except (TypeError, ValueError):
            return 3

    @retry_attempts.setter
    def retry_attempts(self, value):
        self._set("measurement/retry_attempts", int(value))

    @property
    def retry_wait_s(self):
        """Seconds to wait before the first retry (the n-th retry waits n times as long)."""
        try:
            return min(max(float(self._get("measurement/retry_wait_s", 10)), 0.0), 3600.0)
        except (TypeError, ValueError):
            return 10.0

    @retry_wait_s.setter
    def retry_wait_s(self, value):
        self._set("measurement/retry_wait_s", float(value))

    @property
    def past_cache_mb(self):
        """Memory (MiB) the live plot may use for the earlier runs drawn faded behind the current curve."""
        try:
            return min(max(int(self._get("measurement/past_cache_mb", 256)), 16), 8192)
        except (TypeError, ValueError):
            return 256

    @past_cache_mb.setter
    def past_cache_mb(self, value):
        self._set("measurement/past_cache_mb", int(value))

    # ----- alarms on parameters -----
    @property
    def alarm_action(self):
        """What an alarm does besides showing a message: "message", "pause", "stop" or "stop_ramp"."""
        action = self._get("alarms/action", "message")
        return action if action in ("message", "pause", "stop", "stop_ramp") else "message"

    @alarm_action.setter
    def alarm_action(self, value):
        self._set("alarms/action", value if value in ("message", "pause", "stop", "stop_ramp") else "message")

    @property
    def alarm_percent(self):
        """The alarm goes off at this percentage of the allowed values (default 90)."""
        try:
            return min(max(float(self._get("alarms/percent", 90)), 1.0), 100.0)
        except (TypeError, ValueError):
            return 90.0

    @alarm_percent.setter
    def alarm_percent(self, value):
        self._set("alarms/percent", float(value))

    # ----- the queue, kept as it changes (crash recovery) -----
    def queue_autosave(self):
        data = self._get("queue/autosave", {})
        return data if isinstance(data, dict) else {}

    def set_queue_autosave(self, data):
        self._set("queue/autosave", data)

    # ----- QCoDeS configuration chosen by the user ("section.key" -> value) -----
    def qcodes_overrides(self):
        data = self._get("qcodes/overrides", {})
        return data if isinstance(data, dict) else {}

    def set_qcodes_overrides(self, overrides):
        self._set("qcodes/overrides", dict(overrides))
