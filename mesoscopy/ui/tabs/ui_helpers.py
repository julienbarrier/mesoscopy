"""Shared UI helper functions for tabs."""
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel


def set_groupbox_title_bold(group_box: QGroupBox) -> None:
    """Make only the GroupBox title bold using a stylesheet."""
    group_box.setStyleSheet("QGroupBox::title { font-weight: bold; }")


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