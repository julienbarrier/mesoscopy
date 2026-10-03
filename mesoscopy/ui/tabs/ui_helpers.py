"""Shared UI helper functions for tabs."""
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel
from PyQt6.QtCore import QEvent, QObject, Qt


def set_groupbox_title_bold(group_box: QGroupBox) -> None:
    """Make only the GroupBox title bold using a stylesheet."""
    group_box.setStyleSheet("QGroupBox::title { font-weight: bold; }")


def make_text_selectable(label: QLabel) -> QLabel:
    """Allow text in a label to be selected without making it editable."""
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label


def add_labeled_row(parent_layout, label_text, widget, *, stretch=True) -> QHBoxLayout:
    """Add a labeled row (label + widget) to a parent layout."""
    row = QHBoxLayout()
    row.addWidget(QLabel(label_text))
    row.addWidget(widget)
    if stretch:
        row.addStretch()
    parent_layout.addLayout(row)
    return row


def update_parameter_form(experiment_class, form_layout):
    """Populate a form layout from an experiment class definition."""
    while form_layout.rowCount() > 0:
        form_layout.removeRow(0)

    param_widgets = []
    for param_def in experiment_class.parameters:
        label = param_def['name']
        widget = experiment_class.get_widget(param_def)
        if 'default' in param_def:
            param_type = param_def.get('type', 'str')
            if param_type in ('int', 'float'):
                widget.setValue(param_def['default'])
            else:
                widget.setText(str(param_def['default']))
        form_layout.addRow(label, widget)
        param_widgets.append(widget)

    return param_widgets


def get_parameters_from_widgets(experiment_class, param_widgets):
    """Extract parameter values from form widgets."""
    kwargs = {}

    for i, param_def in enumerate(experiment_class.parameters):
        widget = param_widgets[i]
        param_name = param_def['name']
        param_type = param_def.get('type', 'str')
        if param_type == 'int':
            kwargs[param_name] = widget.value()
        elif param_type == 'float':
            kwargs[param_name] = widget.value()
        else:
            kwargs[param_name] = widget.text()

    return kwargs

class _HiddenPauser(QObject):
    """Runs a timer only while a widget is shown. Start and stop the timer through ``start(ms)`` and ``stop()`` of this
    object: a start while the widget is hidden waits until it is shown; hiding the widget stops the timer, showing it again
    restarts it, and ``on_show`` is called then to bring the display up to date."""

    def __init__(self, widget, timer, on_show=None):
        super().__init__(widget)
        self._widget, self._timer, self._on_show = widget, timer, on_show
        self._wanted = timer.isActive()  # the timer is supposed to run (whether or not the widget is shown)
        widget.installEventFilter(self)

    def start(self, interval_ms=None):
        if interval_ms is not None:
            self._timer.setInterval(interval_ms)
        self._wanted = True
        if self._widget.isVisible():
            self._timer.start()

    def stop(self):
        self._wanted = False
        self._timer.stop()

    def eventFilter(self, watched, event):
        try:
            if event.type() == QEvent.Type.Hide and self._timer.isActive():
                self._timer.stop()
            elif event.type() == QEvent.Type.Show and self._wanted and not self._timer.isActive():
                self._timer.start()
                if self._on_show:
                    self._on_show()
        except RuntimeError:
            pass  # the timer was deleted with its window
        return False


def pause_when_hidden(widget, timer, on_show=None):
    """A timer that only runs while ``widget`` is shown (see ``_HiddenPauser``). Returns the object to start and stop it
    with."""
    return _HiddenPauser(widget, timer, on_show)
