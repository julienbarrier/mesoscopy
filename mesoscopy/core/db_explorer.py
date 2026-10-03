"""Read-only browsing of QCoDeS databases: experiments and their runs (no Qt)."""
import os
from datetime import datetime

from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect
from qcodes.dataset.sqlite.queries import (
    get_experiment_attributes_by_exp_id, get_experiments, get_runs,
)


_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RUN_COLUMNS = ("ID", "Name", "Started", "Status", "Points")  # of the table listing the runs of an experiment


def _format_time(timestamp):
    """Epoch seconds -> 'YYYY-MM-DD HH:MM:SS' ('' if missing)."""
    return datetime.fromtimestamp(timestamp).strftime(_TIME_FORMAT) if timestamp else ""


def describe_error(exc):
    """Message of the innermost exception (QCoDeS wraps failures in 'Rolling back ...')."""
    while exc.__cause__ is not None or exc.__context__ is not None:
        exc = exc.__cause__ or exc.__context__
    return str(exc)


def list_db_files(folder):
    """Names of the database files (.db) of a folder, sorted ([] if the folder does not exist)."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.endswith(".db"))


def list_experiments(db_path):
    """Experiments of a database as dicts (exp_id, name, sample_name, start_time, n_runs).

    The database is opened read-only and the global QCoDeS database location is not changed.
    """
    conn = connect(db_path, read_only=True)
    try:
        experiments = []
        for exp_id in get_experiments(conn):
            attrs = get_experiment_attributes_by_exp_id(conn, exp_id)
            experiments.append({
                "exp_id": exp_id,
                "name": attrs["name"],
                "sample_name": attrs["sample_name"],
                "start_time": _format_time(attrs["start_time"]),
                "n_runs": len(get_runs(conn, exp_id)),
            })
        return experiments
    finally:
        conn.close()


def list_runs(db_path, exp_id):
    """Runs of one experiment as dicts (run_id, name, started, completed, n_results, tag, notes)."""
    conn = connect(db_path, read_only=True)
    try:
        runs = []
        for run_id in get_runs(conn, exp_id):
            ds = load_by_id(run_id, conn=conn)
            runs.append({
                "run_id": ds.captured_run_id,
                "name": ds.name,
                "started": ds.run_timestamp(_TIME_FORMAT) or "",
                "completed": bool(ds.completed),
                "n_results": ds.number_of_results,
                "tag": str(ds.metadata.get("tag", "") or ""),      # a colour name, or ""
                "notes": str(ds.metadata.get("notes", "") or ""),
            })
        return runs
    finally:
        conn.close()
