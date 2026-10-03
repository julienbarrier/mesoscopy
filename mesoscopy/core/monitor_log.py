"""The Monitor's log on disk: one tab-separated file, a column per monitored parameter (no Qt).

``monitor_<database>_<yyyymmdd>.log`` in the QCoDeS log folder, e.g. ``monitor_DB012_00_20261003.log``. The first column is
the time; the others are the monitored parameters, in the order of the Monitor tab. A new file is started whenever the
folder, the database or the list of monitored parameters changes (the columns would no longer match). If a file of that
name exists already with the same columns (the application was restarted), the rows are added to it; if it has other
columns, the new file gets the time in its name too (``..._20261003_142530.log``): nothing is ever overwritten.
"""
import os
from datetime import datetime

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SEPARATOR = "\t"


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:.10g}"
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ")


class MonitorLog:
    def __init__(self):
        self._key = None        # (folder, database, columns): the target of the file in use
        self.path = None        # the file rows are added to, None while nothing is logged
        self.columns = ()
        self.started = None     # when this file was started (the application's clock)

    @staticmethod
    def file_name(database, when):
        return f"monitor_{database}_{when:%Y%m%d}.log"

    @staticmethod
    def header(columns):
        return SEPARATOR.join(["timestamp", *columns])

    def configure(self, folder, database, columns, now=None):
        """Point the log at ``folder`` / ``database`` / ``columns``. Returns True when that is a new file (a change of
        target), False when nothing changed. Without a folder or without columns nothing is logged."""
        key = (folder or "", database, tuple(columns))
        if key == self._key:
            return False
        self._key, self.columns = key, tuple(columns)
        self.path, self.started = None, now or datetime.now()
        if not folder or not columns:
            return True
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, self.file_name(database, self.started))
        header = self.header(columns)
        path = base
        if os.path.exists(path) and self._first_line(path) != header:  # another set of columns: a file of its own
            stem, ext = os.path.splitext(base)
            path = f"{stem}_{self.started:%H%M%S}{ext}"
            counter = 1
            while os.path.exists(path) and self._first_line(path) != header:
                counter += 1
                path = f"{stem}_{self.started:%H%M%S}_{counter}{ext}"
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + "\n")
        self.path = path
        return True

    @staticmethod
    def _first_line(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.readline().rstrip("\n")
        except OSError:
            return None

    def write(self, values, when=None):
        """Add a row: ``values`` = {column: value}; a missing one is left empty. Returns the path, None if nothing is logged.
        Raises OSError when the file cannot be written."""
        if self.path is None:
            return None
        row = [(when or datetime.now()).strftime(TIME_FORMAT), *(_cell(values.get(c)) for c in self.columns)]
        with open(self.path, "a", encoding="utf-8") as f:  # opened for each row: a crash loses nothing, rows are rare
            f.write(SEPARATOR.join(row) + "\n")
        return self.path
