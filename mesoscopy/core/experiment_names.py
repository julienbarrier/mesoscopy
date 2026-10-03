"""The experiment names of the databases of a folder, cached in a JSON file of that folder (no Qt).

Listing the experiments of every database each time the Measurement tab needs them would open all of them. The names
are kept in ``experiment_names.json`` in the database folder: a database is read again only when it changed (its size
and date, the write-ahead log included), and a name is added when a measurement creates a new experiment.
"""
import json
import os

from mesoscopy.core.db_explorer import list_db_files, list_experiments

CACHE_FILE = "experiment_names.json"
CACHE_VERSION = 1


def _signature(path):
    """(date, size) of a database and of its write-ahead log: changes when something was written."""
    date, size = 0.0, 0
    for name in (path, path + "-wal"):
        try:
            date = max(date, os.path.getmtime(name))
            size += os.path.getsize(name)
        except OSError:
            pass
    return [date, size]


class ExperimentNameCache:
    """The experiment names of the databases of ``folder``, and the last one used."""

    def __init__(self, folder):
        self.folder = folder
        self.last_used = ""
        self.databases = {}  # file name -> {"signature": [date, size], "experiments": [names]}
        self.reads = 0       # how many databases were read (the rest came from the cache)
        self._load()

    @property
    def path(self):
        return os.path.join(self.folder, CACHE_FILE)

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            if data.get("version") == CACHE_VERSION:
                self.last_used = str(data.get("last_used", ""))
                self.databases = {k: v for k, v in data.get("databases", {}).items()
                                  if isinstance(v, dict) and isinstance(v.get("experiments"), list)}
        except (OSError, ValueError, AttributeError):
            pass  # no cache yet, or an unreadable one: it is made again

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump({"version": CACHE_VERSION, "last_used": self.last_used, "databases": self.databases}, f,
                          indent=2)
        except OSError:
            pass  # a folder that cannot be written: the cache then lives in memory only

    def scan(self):
        """Bring the cache up to date with the databases of the folder: read those that are new or changed, forget
        those that are gone. A database that cannot be read keeps no names. Returns True if anything changed."""
        files = list_db_files(self.folder)
        changed = False
        for name in [n for n in self.databases if n not in files]:
            del self.databases[name]
            changed = True
        for name in files:
            path = os.path.join(self.folder, name)
            entry = self.databases.get(name)
            if entry is not None and entry.get("signature") == _signature(path):
                continue
            try:
                names = [e["name"] for e in list_experiments(path)]
            except Exception:
                names = []
            self.reads += 1
            # the signature is taken after reading: opening a database can merge its write-ahead log into the file
            self.databases[name] = {"signature": _signature(path), "experiments": names}
            changed = True
        if changed:
            self.save()
        return changed

    def names(self, selected_db=None):
        """All the experiment names of the folder, those of the database ``selected_db`` first, without repeats."""
        ordered = ([selected_db] if selected_db in self.databases else []) + \
                  [n for n in sorted(self.databases) if n != selected_db]
        names = []
        for db in ordered:
            names += [n for n in self.databases[db]["experiments"] if n not in names]
        return names

    def record(self, experiment, db_file):
        """A measurement uses the experiment ``experiment`` in the database ``db_file``: remember it as the last used,
        and add it to the names of that database."""
        name = os.path.basename(db_file)
        entry = self.databases.setdefault(name, {"signature": [0.0, 0], "experiments": []})
        if experiment not in entry["experiments"]:
            entry["experiments"].append(experiment)
        self.last_used = experiment
        self.save()
