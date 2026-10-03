"""The "Measured Parameters" box of the Measurement tab: a list of the parameters read at every point."""
import html
import re

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QApplication,
)

from mesoscopy.core.trace_parameter import is_trace, trace_points
from mesoscopy.ui.tabs.component_selector import ComponentSelector, is_gettable
from mesoscopy.ui.tabs.ui_helpers import set_groupbox_title_bold

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ROLE_DATA = Qt.ItemDataRole.UserRole  # {"alias": str, "path": [experiment parameter name]}


class TwoLineDelegate(QStyledItemDelegate):
    """An item as two lines: the name in bold, then, smaller and fainter, where it comes from. The text of the item is
    "name\\ndetail"; a grey foreground (a parameter that is not available) greys both lines."""

    def sizeHint(self, option, index):
        return QSize(100, option.fontMetrics.height() * 2 + 10)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # the item text as set: the delegate's option text has its line breaks replaced
        title, _, detail = str(index.data(Qt.ItemDataRole.DisplayRole) or "").partition("\n")
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)  # background, selection
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        if opt.state & QStyle.StateFlag.State_Selected:
            color = opt.palette.highlightedText().color()
        elif isinstance(brush, QBrush) and brush.style() != Qt.BrushStyle.NoBrush:
            color = brush.color()
        else:
            color = opt.palette.text().color()
        faded = QColor(color)
        faded.setAlpha(170)
        document = QTextDocument()
        document.setDefaultFont(opt.font)
        document.setHtml(
            f"<div style='color:{color.name()};'><b>{html.escape(title)}</b><br>"
            f"<span style='color:{faded.name(QColor.NameFormat.HexArgb)}; font-size:small;'>{html.escape(detail)}</span></div>"
        )
        document.setDocumentMargin(0)
        document.setTextWidth(-1)  # one line each: what does not fit is cut at the edge
        rect = opt.rect.adjusted(8, 4, -8, -4)
        painter.save()
        painter.translate(rect.left(), rect.top())
        painter.setClipRect(QRectF(0, 0, rect.width(), rect.height()))
        document.drawContents(painter)
        painter.restore()


class MeasuredParameterDialog(QDialog):
    """Pick a gettable experiment parameter and, optionally, the name it gets in the dataset (its alias)."""

    def __init__(self, parent, components, taken_names, alias="", path=None, title="Add a measured parameter"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._taken = set(taken_names)  # names already used by the other measured parameters
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.selector = ComponentSelector(param_filter=is_gettable, empty_text="No experiment parameters")
        self.selector.set_root(components)
        if path:
            self.selector.set_path(path)
        form.addRow("Parameter:", self.selector)
        self.alias_edit = QLineEdit(alias)
        self.alias_edit.setPlaceholderText("optional: the name in the dataset")
        self.alias_edit.setToolTip("The measured parameter is saved under this name. Left empty, it keeps its own name.")
        form.addRow("Alias:", self.alias_edit)
        self.trace_note = QLabel("A trace is saved under its own name, together with its axis: no alias.")
        self.trace_note.setStyleSheet("color: gray; font-size: 0.9em;")
        self.trace_note.setWordWrap(True)
        form.addRow("", self.trace_note)
        self.selector.selectionChanged.connect(self._update_alias)
        self._update_alias()
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c00;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_alias(self):
        """A trace cannot have an alias (it would lose its axis): the field is disabled for it."""
        trace = self.selector.parameter() is not None and is_trace(self.selector.parameter())
        self.alias_edit.setEnabled(not trace)
        self.trace_note.setVisible(trace)
        if trace:
            self.alias_edit.clear()

    def accept(self):
        parameter, alias = self.selector.parameter(), self.alias_edit.text().strip()
        if parameter is None:
            self.error_label.setText("Select a parameter.")
            return
        if alias and not _NAME.match(alias):
            self.error_label.setText("The alias must be a name: letters, digits and underscores, not starting with a digit.")
            return
        name = alias or dataset_name(parameter)
        if name in self._taken:
            self.error_label.setText(f"'{name}' is already measured: give another alias.")
            return
        super().accept()

    def result_data(self):
        return {"alias": self.alias_edit.text().strip(), "path": self.selector.path()}


def dataset_name(parameter, alias=""):
    """The name a measured parameter has in the dataset: its alias, or its own name. A trace has no alias: it keeps the
    name under which QCoDeS registers it, with its axis."""
    if is_trace(parameter):
        return parameter.register_name
    return alias or parameter.full_name


class MeasuredParametersBox(QGroupBox):
    """The measured parameters as a list, like the connected instruments of the Instruments tab.

    Each item shows the name it gets in the dataset and the experiment parameter behind it. Add with the button,
    edit with a double click (or the button, or the right-click menu), remove with Delete (or the button), reorder
    by dragging. An item whose parameter is not available (its instrument is not connected) stays, greyed, and
    becomes active again when the parameter is back: a restored measurement does not lose its list.
    """

    def __init__(self, services):
        super().__init__("Measured Parameters")
        set_groupbox_title_bold(self)
        self.services = services
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)  # the order is the order of the dataset
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemDoubleClicked.connect(self.edit_item)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_selected)
        layout.addWidget(self.list, 1)  # takes the height that is left

        self.hint = QLabel("Double-click to edit, drag to reorder, Delete to remove.")
        self.hint.setStyleSheet("color: gray; font-size: 0.9em;")
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add parameter...")
        self.add_button.clicked.connect(self.add_with_dialog)
        self.edit_button = QPushButton("Edit...")
        self.edit_button.clicked.connect(self.edit_selected)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        for button in (self.add_button, self.edit_button, self.remove_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.setMinimumHeight(150)
        self._update_buttons()

    # ----- the items -----
    def _components(self):
        return self.services.registry.parameters()

    def _parameter(self, path):
        """The experiment parameter at ``path`` if it is available and can be read, else None."""
        parameter = self._components().get(path[0]) if path else None
        return parameter if parameter is not None and is_gettable(parameter) else None

    def _effective_names(self, skip=None):
        """The dataset names in use: alias, or the parameter's own name (``skip``: an item being edited)."""
        names = set()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item is skip:
                continue
            data = item.data(ROLE_DATA)
            parameter = self._parameter(data["path"])
            names.add(dataset_name(parameter, data["alias"]) if parameter is not None
                      else (data["alias"] or data["path"][0]))
        return names

    def _show(self, item):
        """Text, colour and tooltip of an item from its data and the availability of its parameter."""
        data = item.data(ROLE_DATA)
        parameter = self._parameter(data["path"])
        name = data["alias"] or data["path"][0]
        if parameter is None:
            item.setText(f"{name}\nnot available: is its instrument connected?")
            item.setForeground(QBrush(Qt.GlobalColor.gray))
            item.setToolTip(f"{data['path'][0]} is not an available experiment parameter at the moment.")
            return
        unit = f" [{parameter.unit}]" if parameter.unit else ""
        origin = "measured under its own name" if not data["alias"] else f"from {parameter.full_name}"
        if is_trace(parameter):
            points = trace_points(parameter)
            origin = f"trace{f' of {points} points' if points else ''}, saved as {parameter.register_name}"
            name = data["path"][0]
        item.setText(f"{name}\n{origin}{unit}")
        item.setForeground(QBrush())  # the normal text colour
        item.setToolTip(f"{parameter.full_name}{unit}" + (f", saved as '{data['alias']}'" if data["alias"] else ""))

    def add(self, path, alias=""):
        """Add a measured parameter given by the name of its experiment parameter (and an alias)."""
        item = QListWidgetItem()
        item.setData(ROLE_DATA, {"alias": alias, "path": list(path)})
        self.list.addItem(item)
        self._show(item)
        return item

    def refresh(self):
        """The experiment parameters changed: show again which items are available."""
        for i in range(self.list.count()):
            self._show(self.list.item(i))

    # ----- editing -----
    def add_with_dialog(self):
        dialog = MeasuredParameterDialog(self, self._components(), self._effective_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.result_data()
            item = self.add(data["path"], data["alias"])
            self.list.clearSelection()
            item.setSelected(True)  # the new one is the selected one
            self.list.setCurrentItem(item)

    def edit_selected(self):
        items = self.list.selectedItems()
        if len(items) == 1:
            self.edit_item(items[0])

    def edit_item(self, item):
        data = item.data(ROLE_DATA)
        dialog = MeasuredParameterDialog(
            self, self._components(), self._effective_names(skip=item), alias=data["alias"], path=data["path"],
            title="Edit the measured parameter",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item.setData(ROLE_DATA, dialog.result_data())
            self._show(item)

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _update_buttons(self):
        selected = len(self.list.selectedItems())
        self.edit_button.setEnabled(selected == 1)
        self.remove_button.setEnabled(selected >= 1)

    def _context_menu(self, position):
        menu = QMenu(self.list)
        item = self.list.itemAt(position)
        if item is not None and not item.isSelected():
            self.list.setCurrentItem(item)
        menu.addAction("Add parameter...").triggered.connect(self.add_with_dialog)
        if item is not None:
            menu.addAction("Edit...").triggered.connect(self.edit_selected)
            menu.addAction("Remove").triggered.connect(self.remove_selected)
        menu.exec(self.list.viewport().mapToGlobal(position))

    # ----- for the measurement -----
    def measured(self):
        """[(name in the dataset, parameter)] in list order. Raises ValueError if one is not available."""
        measured = []
        for i in range(self.list.count()):
            data = self.list.item(i).data(ROLE_DATA)
            parameter = self._parameter(data["path"])
            if parameter is None:
                raise ValueError(f"Measured parameter '{data['alias'] or data['path'][0]}' is not available: "
                                 "connect its instrument or remove it from the list.")
            measured.append((dataset_name(parameter, data["alias"]), parameter))
        return measured

    def get_state(self):
        return [dict(self.list.item(i).data(ROLE_DATA)) for i in range(self.list.count())]

    def set_state(self, entries):
        """Replace the list by ``get_state()`` data. Returns the problems: the parameters not available now (they stay
        in the list, greyed)."""
        self.list.clear()
        problems = []
        for entry in entries:
            path = entry.get("path") or []
            if not path:
                continue  # nothing to measure
            self.add(path, entry.get("alias", ""))
            if self._parameter(path) is None:
                problems.append(f"{path[0]} is not available as a measured parameter")
        return problems
