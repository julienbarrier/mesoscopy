"""Cascading selector that drills down station components until a Parameter is reached."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QComboBox
from qcodes.parameters import ParameterBase
from qcodes.validators import Numbers

from mesoscopy.core.parameter_io import get_children, zhinst_node_is_read_only  # noqa: F401  (get_children is also used by other modules)

_BRANCH_MARK = " ▸"  # shown after entries that have sub-components


def is_gettable(parameter):
    """Filter: parameters whose value can be read."""
    return bool(parameter.gettable)


def is_settable_numeric(parameter):
    """Filter: settable parameters with a unit (V, Hz, ...) or a ``Numbers`` validator.

    The unit is what identifies numeric parameters on drivers without validators
    (e.g. zhinst-qcodes, where ``vals`` is None). Read-only zhinst nodes are excluded.
    """
    if not parameter.settable or zhinst_node_is_read_only(parameter):
        return False
    return bool((parameter.unit or "").strip()) or isinstance(parameter.vals, Numbers)


class ComponentSelector(QWidget):
    """Row of QComboBoxes; each selection adds a combo for the next level.

    The chain ends when the selected item is a QCoDeS Parameter (or has no
    sub-components). Emits ``selectionChanged`` whenever the selection changes.

    ``param_filter`` is an optional callable ``parameter -> bool``. Only parameters
    for which it returns True are offered, and sub-components that contain no such
    parameter are hidden.
    """

    selectionChanged = pyqtSignal()

    def __init__(self, param_filter=None, empty_text=None, parent=None):
        super().__init__(parent)
        self._param_filter = param_filter
        self._empty_text = empty_text
        self._match_cache = {}
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._root = {}
        self._combos = []
        self._add_empty_combo()

    def set_root(self, components):
        """Set the top-level {name: component} mapping (e.g. ``station.components``).

        The previous selection is kept as far as it is still valid.
        """
        previous = self.path()
        self._match_cache = {}
        self._root = self._visible_children_of(components or {})
        self._reset()
        for name in previous:
            combo = self._combos[-1]
            index = combo.findData(name)
            if index < 0:
                break
            combo.setCurrentIndex(index)

    def set_path(self, path):
        """Select the parameter at ``path`` (names from the top-level component down).

        Returns False if the path is not available (the selection stops where it breaks).
        """
        self._reset()
        for name in path:
            index = self._combos[-1].findData(name)
            if index < 0:
                return False
            self._combos[-1].setCurrentIndex(index)
        return True

    def clear(self):
        self.set_root({})

    def path(self):
        """Names selected so far, from the top-level component downwards."""
        return [c.currentData() for c in self._combos if c.currentData() is not None]

    def component(self):
        """The object at the end of the current selection (may not be a Parameter)."""
        children = self._root
        obj = None
        for name in self.path():
            obj = children.get(name)
            if obj is None:
                return None
            children = get_children(obj)
        return obj

    def parameter(self):
        """The selected QCoDeS Parameter, or None while the selection is incomplete."""
        obj = self.component()
        return obj if isinstance(obj, ParameterBase) else None

    def _has_match(self, obj):
        """True if ``obj`` is an accepted parameter or contains one (memoized)."""
        key = id(obj)
        if key not in self._match_cache:
            if isinstance(obj, ParameterBase):
                self._match_cache[key] = self._param_filter is None or bool(self._param_filter(obj))
            else:
                self._match_cache[key] = False  # guards against cycles while recursing
                self._match_cache[key] = any(self._has_match(c) for c in get_children(obj).values())
        return self._match_cache[key]

    def _visible_children_of(self, children):
        if self._param_filter is None:
            return dict(children)
        return {name: child for name, child in children.items() if self._has_match(child)}

    def _reset(self):
        self._remove_combos_from(0)
        if self._root:
            self._add_combo(self._root)
        else:
            self._add_empty_combo()
        self.selectionChanged.emit()

    def _add_empty_combo(self):
        """Disabled placeholder shown while nothing is available to select."""
        combo = QComboBox()
        combo.setPlaceholderText(
            self._empty_text or ("No matching parameters" if self._param_filter else "No instruments loaded")
        )
        combo.setEnabled(False)
        self._layout.addWidget(combo)
        self._combos.append(combo)

    def _add_combo(self, children):
        combo = QComboBox()
        combo.setPlaceholderText("Select...")
        combo.blockSignals(True)
        for name in sorted(children):
            label = name + (_BRANCH_MARK if self._visible_children_of(get_children(children[name])) else "")
            combo.addItem(label, name)
        combo.setCurrentIndex(-1)
        combo.blockSignals(False)
        combo.currentIndexChanged.connect(lambda _i, c=combo: self._on_selected(c))
        self._layout.addWidget(combo)
        self._combos.append(combo)

    def _remove_combos_from(self, index):
        for combo in self._combos[index:]:
            self._layout.removeWidget(combo)
            combo.hide()
            combo.deleteLater()
        del self._combos[index:]

    def _on_selected(self, combo):
        level = self._combos.index(combo)
        self._remove_combos_from(level + 1)
        obj = self.component()
        children = self._visible_children_of(get_children(obj)) if obj is not None else {}
        if children:
            self._add_combo(children)
        self.selectionChanged.emit()
