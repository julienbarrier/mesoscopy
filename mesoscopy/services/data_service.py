"""Where the data of the measurements goes: the database folder, the sample and the selected database (no widgets).

The Data tab shows and edits these; the run controller and the snapshot loader read them. There is one database in
use at any time: the one selected in the Data tab. The explorer, the live plot, "Load Snapshot" and the runs all use
it; a run that needs another (a new one, or the next of a full one) has it selected first.
"""
from PyQt6.QtCore import QObject, pyqtSignal

from mesoscopy.core.db_manager import database_for_run


class DataService(QObject):
    sampleChanged = pyqtSignal(str)  # the sample was set from outside the Data tab (e.g. by Load Snapshot)
    locationChanged = pyqtSignal()    # the database folder or the selected database changed
    entryChanged = pyqtSignal()       # the folder, the selected database or the sample name changed
    runMetadataChanged = pyqtSignal(str, int, str, str)  # database file, run id (as the explorer lists it), "tag" or "notes", the new value
    databaseChosen = pyqtSignal(str)  # a run needs this database (a new one, or the next of a full one): the Data tab
                                      # creates it and selects it, so the selected database is always the one in use

    def __init__(self):
        super().__init__()
        self.folder = ""            # database folder
        self.sample_name = ""
        self.selected_file = None   # path of the database chosen in the Data tab; None: "a new database"
        self.last_note = ""         # why a database other than the selected one is used (size limit), or ""

    @property
    def has_database(self):
        """A database is entered: a folder, and a database selected in it or a sample name to name a new one after."""
        return bool(self.folder) and (bool(self.selected_file) or bool(self.sample_name.strip()))

    def set_sample_name(self, name):
        """Set the sample from outside the Data tab; the tab shows it."""
        if name != self.sample_name:
            self.sample_name = name
            self.sampleChanged.emit(name)

    def select_database(self, path):
        """Make ``path`` the selected database (the Data tab creates it if it is new). A no-op if it is selected."""
        if path != self.selected_file:
            self.databaseChosen.emit(path)

    def database_for_run(self):
        """Path of the database the next run writes to, named after the sample (see ``db_manager``).

        Raises ValueError with a readable message."""
        if not self.folder:
            raise ValueError("Select a database folder in the Data tab.")
        path, self.last_note = database_for_run(self.folder, self.selected_file, self.sample_name)
        return path
