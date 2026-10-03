"""Naming, rotation and creation of the measurement databases of a folder (no Qt).

Databases are named after the sample: ``<sample>_<NN>.db`` with NN two digits (``Hall_bar_00.db``). The first one
of a sample is 00; a new one is the highest existing NN of that sample plus one. A database that grew above
``DB_LIMIT_BYTES`` is not written to any more: the next run starts the next one. The user never types a name.
"""
import os
import re

from qcodes.dataset.sqlite.database import connect
from qcodes.dataset.sqlite.initial_schema import init_db

DB_LIMIT_BYTES = 750 * 1024 ** 2
_NUMBERED = re.compile(r"^(?P<prefix>.+)_(?P<index>\d{2,})\.db$")


def sample_prefix(sample):
    """The sample name as it is used in a file name (spaces and other unsafe characters become '_'); '' if empty."""
    return re.sub(r"[^\w.\-]+", "_", (sample or "").strip()).strip("_.")


def database_name(prefix, index):
    return f"{prefix}_{index:02d}.db"


def prefix_of(filename):
    """The sample prefix of a database named ``<prefix>_<NN>.db``, or None for any other file name."""
    match = _NUMBERED.match(os.path.basename(filename))
    return match.group("prefix") if match else None


def existing_indices(folder, prefix):
    """The NN of the databases ``<prefix>_<NN>.db`` of the folder, sorted."""
    if not folder or not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        match = _NUMBERED.match(name)
        if match and match.group("prefix") == prefix:
            found.append(int(match.group("index")))
    return sorted(found)


def next_database(folder, prefix):
    """Path of the database a new one of ``prefix`` is: index 0 if there is none, else the highest plus one."""
    indices = existing_indices(folder, prefix)
    return os.path.join(folder, database_name(prefix, indices[-1] + 1 if indices else 0))


def latest_database(folder, prefix):
    """Path of the highest-numbered database of ``prefix``, or None."""
    indices = existing_indices(folder, prefix)
    return os.path.join(folder, database_name(prefix, indices[-1])) if indices else None


def size_bytes(path):
    """Size of a database, counting its write-ahead log (data not yet merged into the main file)."""
    total = 0
    for name in (path, path + "-wal"):
        try:
            total += os.path.getsize(name)
        except OSError:
            pass
    return total


def megabytes(size):
    return f"{size / 1024 ** 2:.0f} MB"


def _prefix_for(selected, sample):
    """Prefix a new database follows: the one of the selected file (if it is numbered), else the sample's."""
    prefix = prefix_of(selected) if selected else None
    prefix = prefix or sample_prefix(sample)
    if not prefix:
        raise ValueError("Enter a sample name: databases are named after it.")
    return prefix


def database_for_run(folder, selected, sample, limit=None):
    """(path, note) of the database the next run writes to.

    ``selected`` is the database chosen in the Data tab (None: "a new database"). A new database is
    ``<sample>_<NN>.db``. A measurement always goes to the newest database of the series: when the selected one is
    ``<prefix>_<NN>.db`` the run uses the highest NN of that prefix, even if an older one was being browsed, or the
    next number when that highest one is above the size limit. A selected database whose name has no number is used
    as it is (or replaced by the next of the sample's series when it is above the limit).
    ``note`` says why a database other than the selected one is used ('' otherwise). Raises ValueError.
    """
    limit = DB_LIMIT_BYTES if limit is None else limit
    if selected is None:
        return next_database(folder, _prefix_for(None, sample)), ""
    prefix = prefix_of(selected)
    newest = (latest_database(folder, prefix) if prefix else None) or selected  # the highest number of the series
    size = size_bytes(newest)
    if size > limit:
        new = next_database(folder, _prefix_for(newest, sample))
        return new, f"{os.path.basename(newest)} is {megabytes(size)} (limit {megabytes(limit)}): " \
                    f"using the new database {os.path.basename(new)}"
    if newest != selected:
        return newest, f"{os.path.basename(selected)} is not the newest of its series: using {os.path.basename(newest)}"
    return selected, ""


def create_database(path):
    """Create an empty QCoDeS database file with its tables (the global QCoDeS database location is not touched)."""
    conn = connect(path)
    try:
        init_db(conn)
    finally:
        conn.close()
