"""The experiment names offered by the Measurement tab (no widgets).

Follows the database folder and the selected database of the data service, keeps the cache of the folder
(``core.experiment_names``) and adds the experiment of every measurement that starts.
"""
import os

from PyQt6.QtCore import QObject, pyqtSignal

from mesoscopy.core.experiment_names import ExperimentNameCache


class ExperimentNamesService(QObject):
    namesChanged = pyqtSignal()  # the names offered, or the last one used, changed

    def __init__(self, services):
        super().__init__()
        self.services = services
        self._cache = None
        services.data.locationChanged.connect(self._on_location_changed)
        services.run.runStarted.connect(self._on_run_started)

    def _on_location_changed(self):
        folder = self.services.data.folder
        if self._cache is None or self._cache.folder != folder:
            self._cache = ExperimentNameCache(folder) if folder and os.path.isdir(folder) else None
        if self._cache is not None:
            self._cache.scan()  # reads only the databases that are new or changed
        self.namesChanged.emit()

    def _on_run_started(self, session):
        """The measurement creates its experiment (or uses one that exists): remember it."""
        if self._cache is not None and self._cache.folder == os.path.dirname(session.db_file):
            self._cache.record(session.experiment_name, session.db_file)
            self.namesChanged.emit()

    def names(self):
        """The experiment names of the databases of the folder, those of the selected database first."""
        if self._cache is None:
            return []
        selected = self.services.data.selected_file
        return self._cache.names(os.path.basename(selected) if selected else None)

    def last_used(self):
        return self._cache.last_used if self._cache is not None else ""
