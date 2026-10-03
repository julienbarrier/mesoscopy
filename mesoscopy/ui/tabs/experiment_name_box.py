"""The experiment name of the Measurement tab: a dropdown of the experiment names of the database folder."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

NEW_EXPERIMENT = "New Experiment"
DEFAULT_NAME = "Sweep"  # used when a new experiment is left without a name


class ExperimentNameBox(QWidget):
    """A dropdown with the experiment names found in the databases of the folder (those of the selected database
    first, the last one used selected), ending with "New Experiment", which shows a field to type a new name.

    ``text()`` is the name to use, ``setText`` chooses a name (a name that does not exist yet goes to the field).
    The list follows ``services.experiments``.
    """

    changed = pyqtSignal()

    def __init__(self, services):
        super().__init__()
        self.services = services
        self._explicit = False  # the user, or a restored setup, chose a name: a refresh keeps it
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(180)
        self.combo.setToolTip("The experiments of the databases of the folder; the last one used is selected.")
        self.field = QLineEdit()
        self.field.setPlaceholderText(f"Name of the new experiment ({DEFAULT_NAME} if left empty)")
        self.field.setMinimumWidth(220)
        layout.addWidget(self.combo)
        layout.addWidget(self.field, 1)
        self.combo.activated.connect(self._on_chosen)
        self.field.textChanged.connect(lambda _: self.changed.emit())
        services.experiments.namesChanged.connect(self.refresh)
        self.refresh()

    # ----- the list -----
    def _is_new(self):
        return self.combo.currentData() is None

    def _fill(self, names):
        self.combo.blockSignals(True)
        self.combo.clear()
        for name in names:
            self.combo.addItem(name, name)
        self.combo.addItem(NEW_EXPERIMENT, None)  # the last item
        self.combo.blockSignals(False)

    def refresh(self):
        """Show the names that are available now, keeping the choice that was made."""
        current, was_new = self.text(), self._is_new() if self.combo.count() else True
        names = self.services.experiments.names()
        self._fill(names)
        if self._explicit and current and current in names:
            self.combo.setCurrentIndex(names.index(current))
        elif self._explicit and was_new:
            self.combo.setCurrentIndex(self.combo.count() - 1)  # a name being typed stays in the field
        else:
            last = self.services.experiments.last_used()
            default = names.index(last) if last in names else (0 if names else self.combo.count() - 1)
            self.combo.setCurrentIndex(default)
            self._explicit = False
        self._update_field()
        self.changed.emit()

    def _update_field(self):
        self.field.setVisible(self._is_new())

    def _on_chosen(self, _index):
        self._explicit = True
        self._update_field()
        if self._is_new():
            self.field.setFocus()
        self.changed.emit()

    # ----- the name -----
    def text(self):
        """The experiment name: the one chosen, or the one typed for a new experiment."""
        return self.field.text().strip() if self._is_new() else self.combo.currentText()

    def setText(self, name):
        """Choose ``name``: an existing experiment is selected, a new name goes to the New Experiment field."""
        self._explicit = True
        index = self.combo.findData(name) if name else -1
        if index >= 0:
            self.combo.setCurrentIndex(index)
        else:
            self.combo.setCurrentIndex(self.combo.count() - 1)
            self.field.setText(name)
        self._update_field()
        self.changed.emit()
