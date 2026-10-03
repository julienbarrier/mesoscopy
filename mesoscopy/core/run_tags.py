"""Tags and notes of a run, kept in the metadata of the run in the database (no Qt).

A tag is one of a few colours, stored as the colour's name; notes are free text. Both are QCoDeS run metadata
(``dataset.add_metadata``), which can be added at any time, also to a finished run.
"""
from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect

TAGS = ("red", "orange", "yellow", "green", "blue", "purple")
TAG_KEY = "tag"
NOTES_KEY = "notes"


def _write(db_path, run_id, key, value):
    conn = connect(db_path)  # not read-only: the metadata is written
    try:
        load_by_id(run_id, conn=conn).add_metadata(key, value)
    finally:
        conn.close()


def set_tag(db_path, run_id, tag):
    """Tag a run with a colour ("" removes the tag). Raises ValueError for another name."""
    if tag and tag not in TAGS:
        raise ValueError(f"'{tag}' is not a tag: use one of {', '.join(TAGS)}.")
    _write(db_path, run_id, TAG_KEY, tag)


def set_notes(db_path, run_id, notes):
    """Write the notes of a run (empty text removes them)."""
    _write(db_path, run_id, NOTES_KEY, notes)


def get_run_tags(db_path, run_id):
    """(tag, notes) of a run, read without writing ("" for what it does not have)."""
    conn = connect(db_path, read_only=True)
    try:
        metadata = load_by_id(run_id, conn=conn).metadata
        return str(metadata.get(TAG_KEY, "") or ""), str(metadata.get(NOTES_KEY, "") or "")
    finally:
        conn.close()
