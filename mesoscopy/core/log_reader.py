"""Read the QCoDeS log files of a folder (no Qt).

A log line has the format of ``qcodes.logger``: ``time ¦ logger ¦ level ¦ module ¦ function ¦ line ¦ message``.
Lines that follow a record without starting with such a header (tracebacks, multi-line messages) belong to it.
Messages logged for an instrument by QCoDeS start with ``[<instrument>(<class>)]``: that is how a record is
attributed to an instrument, as the live ``filter_instrument`` does with the record's ``instrument_name``.
"""
import glob
import os
import re
from dataclasses import dataclass

from qcodes.logger.logger import LOGGING_SEPARATOR

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
MAX_BYTES = 20 * 1024 * 1024  # of a big file, only the end is read
_INSTRUMENT = re.compile(r"^\[([^\]\(\s]+)\(([^\)]*)\)\]\s?")
_HEADER = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+")


@dataclass
class LogRecord:
    time: str
    logger: str
    level: str
    module: str
    function: str
    line: str
    message: str            # all of it, including a traceback
    instrument: str = ""    # logged instrument (or channel) name, "" when the record is not about an instrument

    @property
    def severity(self):
        return LEVELS.get(self.level, 0)

    def first_line(self):
        return self.message.split("\n", 1)[0]

    def as_text(self):
        return f"{self.time}  {self.level:<8}{self.logger}  {self.message}"


def find_log_files(folder):
    """The QCoDeS log files in ``folder`` (``*qcodes.log*``, rotated ones included), newest first."""
    if not folder or not os.path.isdir(folder):
        return []
    files = [f for f in glob.glob(os.path.join(folder, "*qcodes.log*")) if os.path.isfile(f)]
    return sorted(files, key=os.path.getmtime, reverse=True)


def parse_log(lines):
    """Records of the lines of a log file, in file order. Lines before the first record are ignored."""
    records = []
    for line in lines:
        line = line.rstrip("\n")
        if _HEADER.match(line):
            parts = line.split(LOGGING_SEPARATOR, 6)
            if len(parts) == 7:
                time, logger, level, module, function, number, message = parts
                match = _INSTRUMENT.match(message)
                records.append(LogRecord(time, logger, level, module, function, number, message,
                                         match.group(1) if match else ""))
                continue
        if records:
            records[-1].message += "\n" + line
    return records


def read_log(path, max_bytes=MAX_BYTES):
    """(records, truncated) of a log file; only the last ``max_bytes`` are read from a bigger one."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()  # the first line is cut
        text = f.read().decode("utf-8", errors="replace")
    return parse_log(text.splitlines()), size > max_bytes


def instrument_matches(logged, wanted):
    """A channel or module is logged as ``<instrument>_<name>``: it belongs to its instrument."""
    return logged == wanted or logged.startswith(wanted + "_")


def root_instruments(records, known=()):
    """Instrument names to offer in a filter: those in the records (channels folded into their instrument)
    and the ``known`` ones."""
    names = {r.instrument for r in records if r.instrument} | set(known)
    return sorted(n for n in names if not any(n != o and n.startswith(o + "_") for o in names))


def filter_records(records, instrument="", min_level=0, text=""):
    """Records of ``instrument`` ("": all; None-like "(none)" is handled by the caller) at ``min_level`` or above
    that contain ``text`` (case-insensitive)."""
    needle = text.lower()
    return [r for r in records
            if r.severity >= min_level
            and (not instrument or instrument_matches(r.instrument, instrument))
            and (not needle or needle in r.message.lower() or needle in r.logger.lower())]
