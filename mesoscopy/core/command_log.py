"""Recent commands of the instruments, taken from the QCoDeS logger (no Qt).

QCoDeS logs what it sends to VISA instruments ("Writing: ...", "Querying: ...", "Response: ...") and to IP
instruments, at DEBUG level on loggers below ``qcodes.instrument``. ``CommandLog`` is a logging handler that
keeps the latest records of each instrument in memory so that the application can show them.
Drivers that do not use these loggers (e.g. zhinst) leave nothing here.
"""
import logging
import re
import threading
from collections import defaultdict, deque
from datetime import datetime

LOGGER_NAME = "qcodes.instrument"
MAX_ENTRIES = 2000  # kept per instrument
_IP_INSTRUMENT = re.compile(r"instrument (\S+)$")  # IP instruments log "... to/from instrument <name>"
_ADAPTER_PREFIX = re.compile(r"^\[[^\]]*\]\s*")  # QCoDeS prefixes the messages with "[name(Class)] "


class CommandLog(logging.Handler):
    """Keeps the last ``MAX_ENTRIES`` records of each instrument, whichever thread logged them."""

    _instance = None

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self._lock = threading.Lock()
        self._entries = defaultdict(lambda: deque(maxlen=MAX_ENTRIES))  # logged name -> (time, level, text)
        self._counts = defaultdict(int)

    @classmethod
    def install(cls):
        """Attach the (single) handler to the QCoDeS instrument loggers, and let them emit DEBUG records."""
        if cls._instance is None:
            cls._instance = cls()
            logger = logging.getLogger(LOGGER_NAME)
            logger.addHandler(cls._instance)
            if logger.getEffectiveLevel() > logging.DEBUG:
                logger.setLevel(logging.DEBUG)
        return cls._instance

    def emit(self, record):
        try:
            name = getattr(record, "instrument_name", None)
            if name is None and record.name.endswith(".ip"):
                match = _IP_INSTRUMENT.search(record.getMessage())
                name = match.group(1) if match else None
            if name is None:
                return
            entry = (record.created, record.levelname, _ADAPTER_PREFIX.sub("", record.getMessage()))
            with self._lock:
                self._entries[name].append(entry)
                self._counts[name] += 1
        except Exception:
            self.handleError(record)

    @staticmethod
    def _belongs(logged_name, instrument):
        """A channel or module is logged as ``<instrument>_<name>``."""
        return logged_name == instrument or logged_name.startswith(instrument + "_")

    def entries(self, instrument):
        """(version, [(time, level, text)]) of an instrument and its channels, oldest first. The version
        changes whenever something was logged: compare it to know if a redraw is needed."""
        with self._lock:
            keys = [k for k in self._entries if self._belongs(k, instrument)]
            version = sum(self._counts[k] for k in keys)
            merged = sorted((e for k in keys for e in self._entries[k]), key=lambda e: e[0])
        return version, merged

    def clear(self, instrument):
        with self._lock:
            for key in [k for k in self._entries if self._belongs(k, instrument)]:
                self._entries[key].clear()
                self._counts[key] += 1  # a redraw is needed


def format_entry(entry):
    """'HH:MM:SS.mmm  LEVEL    message'."""
    created, level, text = entry
    return f"{datetime.fromtimestamp(created).strftime('%H:%M:%S.%f')[:-3]}  {level:<7}  {text}"
