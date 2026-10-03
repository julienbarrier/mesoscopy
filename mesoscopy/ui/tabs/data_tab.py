"""Data tab UI components (database and logs)."""
import os

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidgetAction,
)
from mesoscopy.core.db_explorer import RUN_COLUMNS, describe_error, list_db_files, list_experiments, list_runs
from mesoscopy.core.db_manager import (
    DB_LIMIT_BYTES, create_database, latest_database, megabytes, next_database, prefix_of,
    sample_prefix, size_bytes,
)
from mesoscopy.core.logging_setup import start_file_logging
from mesoscopy.core.snapshot_diff import diff_rows, read_run_snapshot
from mesoscopy.core.run_tags import set_notes, set_tag
from mesoscopy.ui.tabs.compare_dialogs import ComparePickerDialog, SnapshotDiffDialog
from mesoscopy.ui.tabs.run_notes import NotesDialog, TagPicker
from mesoscopy.ui.tabs.run_table import ROLE_RUN, fill_run_row, setup_run_table
from mesoscopy.ui.tabs.log_viewer import LogViewerDialog
from mesoscopy.ui.tabs.ui_helpers import make_text_selectable, set_groupbox_title_bold


class DataTab(QObject):
    """Data tab: where the data goes (database folder, sample, database file), the experiment explorer and the logs.

    It owns its widgets. What others need to know about the database choice is published in ``services.data``;
    the tab subscribes to the end of a run (to show it in the explorer) and to the sample being set from outside.
    ``loadSnapshotRequested(db_path, run_id)`` is emitted by the "Load Snapshot" button.
    """

    loadSnapshotRequested = pyqtSignal(str, int)

    def __init__(self, tab_widget, services):
        super().__init__()  # a QObject: it has signals
        self.tab = tab_widget
        self.services = services
        self._log_viewer = None
        self._followed_run = None  # the run the explorer selected by itself (the newest), not one the user chose
        self.setup_ui()
        services.run.runFinished.connect(self._on_run_finished)
        services.run.repetitionFinished.connect(self._on_repetition_finished)
        services.data.sampleChanged.connect(self._on_sample_set_from_outside)
        services.data.databaseChosen.connect(self._on_database_chosen)
        services.data.runMetadataChanged.connect(self._on_run_metadata_changed)

    def setup_ui(self):
        """Set up the data tab UI."""
        main_layout = QHBoxLayout()
        self.tab.setLayout(main_layout)

        data_column = QVBoxLayout()

        # Database and Experiment Info group
        db_group = QGroupBox("Database and Experiment Info")
        set_groupbox_title_bold(db_group)
        db_layout = QFormLayout()
        db_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        db_group.setLayout(db_layout)

        self.db_folder_display = QLineEdit()
        self.db_folder_display.setReadOnly(True)
        self.db_folder_button = QPushButton("Browse...")
        self.db_folder_button.clicked.connect(self.select_db_folder)

        db_folder_layout = QHBoxLayout()
        db_folder_layout.addWidget(self.db_folder_display)
        db_folder_layout.addWidget(self.db_folder_button)

        self.db_file_combo = QComboBox()
        self.db_file_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.db_file_combo.currentIndexChanged.connect(self.on_db_file_changed)

        self.upgrade_db_button = QPushButton("Upgrade database")
        self.services.measuring.gate(self.upgrade_db_button)  # the run writes to the database in use
        self.upgrade_db_button.setToolTip(
            "Start a new database now (the next number of the series), even if this one is below the size limit"
        )
        self.upgrade_db_button.clicked.connect(self.upgrade_database)
        db_file_layout = QHBoxLayout()
        db_file_layout.addWidget(self.db_file_combo, 1)
        db_file_layout.addWidget(self.upgrade_db_button)

        self.db_size_label = QLabel("")
        self.sample_name_input = QLineEdit("")
        self.sample_name_input.setPlaceholderText("Databases are named after the sample")
        self.sample_name_input.textChanged.connect(self.on_sample_changed)

        db_layout.addRow("Database folder:", db_folder_layout)
        db_layout.addRow("Sample name:", self.sample_name_input)
        db_layout.addRow("Database file:", db_file_layout)
        db_layout.addRow("Database size:", self.db_size_label)

        data_column.addWidget(db_group)

        # Logs group
        logs_group = QGroupBox("Logs")
        set_groupbox_title_bold(logs_group)
        logs_layout = QFormLayout()
        logs_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        logs_group.setLayout(logs_layout)

        self.logs_folder_display = QLineEdit()
        self.logs_folder_display.setReadOnly(True)
        self.logs_folder_button = QPushButton("Browse...")
        self.logs_folder_button.clicked.connect(self.select_logs_folder)
        self.logs_folder_display.textChanged.connect(lambda text: self.services.data.set_logs_folder(text.strip()))

        logs_folder_layout = QHBoxLayout()
        logs_folder_layout.addWidget(self.logs_folder_display)
        logs_folder_layout.addWidget(self.logs_folder_button)

        logs_layout.addRow("Logs folder:", logs_folder_layout)

        self.start_logging_button = QPushButton("Start logging")
        self.start_logging_button.clicked.connect(self.start_logging)
        logs_layout.addRow(self.start_logging_button)

        self.view_logs_button = QPushButton("View Logs")
        self.view_logs_button.setToolTip("Browse the QCoDeS logs written to the logs folder")
        self.view_logs_button.clicked.connect(self.view_logs)
        logs_layout.addRow(self.view_logs_button)

        self.logs_error_display = make_text_selectable(QLabel(""))
        self.logs_error_display.setWordWrap(True)
        self.logs_error_display.setStyleSheet("color: #c00; font-size: 0.9em;")
        self.logs_error_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        logs_layout.addRow(self.logs_error_display)

        data_column.addWidget(logs_group)
        data_column.addStretch()

        # Right side - Experiment explorer (filled once a database is loaded)
        explorer_group = QGroupBox("Experiment Explorer")
        set_groupbox_title_bold(explorer_group)
        explorer_layout = QVBoxLayout()
        explorer_group.setLayout(explorer_layout)

        self.experiment_combo = QComboBox()
        self.experiment_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.experiment_combo.setPlaceholderText("Select an experiment")
        self.experiment_combo.currentIndexChanged.connect(self.on_experiment_changed)
        explorer_layout.addWidget(self.experiment_combo)

        self.explorer_message = make_text_selectable(QLabel(""))
        self.explorer_message.setWordWrap(True)
        self.explorer_message.setVisible(False)  # only shown for errors / empty databases
        explorer_layout.addWidget(self.explorer_message)

        self.runs_table = QTableWidget(0, len(RUN_COLUMNS))
        self.runs_table.setHorizontalHeaderLabels(RUN_COLUMNS)
        self.runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        setup_run_table(self.runs_table)  # the tag dot and the note preview in the name cell
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.runs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.runs_table.verticalHeader().setVisible(False)
        header = self.runs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # run name takes the slack
        explorer_layout.addWidget(self.runs_table)
        self.runs_table.itemSelectionChanged.connect(self.on_run_selected)
        self.runs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.runs_table.customContextMenuRequested.connect(self._show_run_menu)

        # always shown, greyed out until a run is selected: compare its snapshot with another run's, or load it
        self.compare_button = QPushButton("Compare with another run")
        self.compare_button.setToolTip("Pick a second run (in any database) and show what differs between the "
                                       "snapshots of the two runs: instrument values, experiment parameters, setup.")
        self.compare_button.setEnabled(False)  # greyed out until a run is selected
        self.compare_button.clicked.connect(self.compare_with_another_run)
        explorer_layout.addWidget(self.compare_button)
        self.load_snapshot_button = QPushButton("Load Snapshot")
        self.load_snapshot_button.setToolTip(
            "Connect the instruments of this run, restore their settings and the experiment parameters, and "
            "set up the Measurement tab as it was. Nothing is run; you review the changes first."
        )
        self.load_snapshot_button.setEnabled(False)
        self.services.measuring.gate(self.load_snapshot_button)  # it sets the instruments
        self.load_snapshot_button.clicked.connect(self._request_snapshot)
        explorer_layout.addWidget(self.load_snapshot_button)

        main_layout.addLayout(data_column, 1)
        main_layout.addWidget(explorer_group, 2)

    def current_db_path(self):
        """Path of the selected existing database file, or None (also for "a new database")."""
        folder = self.db_folder_display.text().strip()
        name = self.db_file_combo.currentData()
        if not folder or not name:
            return None
        path = os.path.join(folder, name)
        return path if os.path.isfile(path) else None

    def _selected_db_file(self):
        """Path chosen in the file selector, even if it does not exist; None for "a new database"."""
        name = self.db_file_combo.currentData()
        folder = self.db_folder_display.text().strip()
        return os.path.join(folder, name) if name and folder else None

    def _publish(self):
        """Tell the data service what the widgets say (the run controller and the snapshot loader read it)."""
        data = self.services.data
        before = (data.folder, data.selected_file)
        entry_before = (data.folder, data.selected_file, data.sample_name)
        data.folder = self.db_folder_display.text().strip()
        data.sample_name = self.sample_name_input.text()
        data.selected_file = self._selected_db_file()
        if (data.folder, data.selected_file) != before:
            data.locationChanged.emit()  # the experiment names offered follow the folder and the database
        if (data.folder, data.selected_file, data.sample_name) != entry_before:
            data.entryChanged.emit()  # the tabs that need a database follow

    # ----- right click on a run: tag, notes, compare, load snapshot -----
    def _show_run_menu(self, position):
        item = self.runs_table.itemAt(position)
        if item is None:
            return
        self.runs_table.selectRow(item.row())
        menu = self.build_run_menu(item.row())
        menu.exec(self.runs_table.viewport().mapToGlobal(position))

    def build_run_menu(self, row):
        """The menu of the run in ``row``: a line of coloured dots (the tag), add or edit notes, delete note, compare
        with another run, load snapshot."""
        run = self.runs_table.item(row, 1).data(ROLE_RUN)
        menu = QMenu(self.runs_table)
        picker = TagPicker(run.get("tag", ""))
        picker.tagChosen.connect(lambda tag, r=row: (menu.close(), self.set_run_tag(r, tag)))
        action = QWidgetAction(menu)
        action.setDefaultWidget(picker)
        menu.addAction(action)
        menu.tag_picker = picker  # for tests and callers that want the dots
        menu.addAction("Edit notes..." if run.get("notes") else "Add notes...").triggered.connect(
            lambda: self.edit_run_notes(row))
        delete = menu.addAction("Delete note")
        delete.setEnabled(bool(run.get("notes")))  # nothing to delete without a note
        delete.triggered.connect(lambda: self.delete_run_notes(row))
        menu.addAction("Compare with another run").triggered.connect(self.compare_with_another_run)
        self.services.measuring.block(menu.addAction("Load snapshot")).triggered.connect(self._request_snapshot)
        return menu

    def _on_run_metadata_changed(self, db_file, run_id, field, value):
        """The tag or the notes of a run were changed elsewhere (the live viewer): show it in the table if it lists that run."""
        shown = self.current_db_path()
        if shown is None or os.path.normcase(os.path.abspath(shown)) != os.path.normcase(os.path.abspath(db_file)):
            return
        for row in range(self.runs_table.rowCount()):
            item = self.runs_table.item(row, 1)
            run = item.data(ROLE_RUN) if item is not None else None
            if run and run.get("run_id") == run_id:
                fill_run_row(self.runs_table, row, dict(run, **{field: value}))
                return

    def _write_run_metadata(self, row, field, value, writer):
        """Write the tag or the notes of the run in ``row`` to its database, then show it in the table."""
        run, db_path = self.runs_table.item(row, 1).data(ROLE_RUN), self.current_db_path()
        if db_path is None:
            return False
        try:
            writer(db_path, run["run_id"], value)
        except Exception as e:  # e.g. the database is locked by a measurement writing at that very moment
            QMessageBox.warning(self.tab.window(), "Run metadata", f"Could not write the {field}: {describe_error(e)}")
            return False
        fill_run_row(self.runs_table, row, dict(run, **{field: value}))
        return True

    def set_run_tag(self, row, tag):
        """Tag the run in ``row`` with a colour; choosing the colour it has already removes the tag."""
        run = self.runs_table.item(row, 1).data(ROLE_RUN)
        tag = "" if tag == run.get("tag", "") else tag
        if self._write_run_metadata(row, "tag", tag, set_tag):
            self.services.status.show(f"Run {run['run_id']}: " + (f"tag {tag}." if tag else "tag removed."), 4000)

    def edit_run_notes(self, row):
        run = self.runs_table.item(row, 1).data(ROLE_RUN)
        dialog = NotesDialog(self.tab.window(), f"Notes of run {run['run_id']}", run.get("notes", ""))
        if dialog.exec() and dialog.notes() != run.get("notes", ""):
            if self._write_run_metadata(row, "notes", dialog.notes(), set_notes):
                self.services.status.show(f"Run {run['run_id']}: notes saved.", 4000)

    def delete_run_notes(self, row):
        """Remove the notes of the run in ``row``."""
        run = self.runs_table.item(row, 1).data(ROLE_RUN)
        if run.get("notes") and self._write_run_metadata(row, "notes", "", set_notes):
            self.services.status.show(f"Run {run['run_id']}: note deleted.", 4000)

    def compare_with_another_run(self):
        """The selected run is run A: pick run B in a dialog (any database, only read), then show what differs
        between the snapshots."""
        run_a, db_a = self.selected_run_id(), self.current_db_path()
        if run_a is None or db_a is None:
            self.services.status.show("Select a run first.", 3000)
            return
        picker = ComparePickerDialog(self.tab.window(), folder=self.db_folder_display.text().strip(),
                                     db_name=os.path.basename(db_a))
        if not picker.exec():
            return
        db_b, run_b = picker.selection()
        try:
            snapshot_a, snapshot_b = read_run_snapshot(db_a, run_a), read_run_snapshot(db_b, run_b)
        except Exception as e:
            QMessageBox.warning(self.tab.window(), "Compare runs", f"Cannot read the runs: {describe_error(e)}")
            return
        missing = [f"run {r.run_id} of {r.db_name}" for r in (snapshot_a, snapshot_b) if r.snapshot is None]
        if missing:
            QMessageBox.warning(self.tab.window(), "Compare runs", "No snapshot stored with " + " and ".join(missing) + ".")
            return
        SnapshotDiffDialog(self.tab.window(), snapshot_a, snapshot_b,
                           diff_rows(snapshot_a.snapshot, snapshot_b.snapshot)).exec()

    def _request_snapshot(self):
        run_id, db_path = self.selected_run_id(), self.current_db_path()
        if run_id is None or db_path is None:
            self.services.status.show("Select a run first.", 3000)
            return
        self.loadSnapshotRequested.emit(db_path, run_id)

    # ----- folders -----
    def _browse(self, field, title, default_kind):
        start = field.text().strip() or self.services.settings.default_folder(default_kind) or "./"
        folder = QFileDialog.getExistingDirectory(self.tab, title, start)
        if folder:
            field.setText(folder)
        return folder

    def select_db_folder(self):
        if self._browse(self.db_folder_display, "Select Database Folder", "database"):
            self.populate_database_files()

    def select_logs_folder(self):
        self._browse(self.logs_folder_display, "Select Logs Folder", "logs")

    def set_db_folder(self, folder):
        """Use ``folder`` as the database folder (ignored if it is not a folder)."""
        if folder and os.path.isdir(folder):
            self.db_folder_display.setText(folder)
            self.populate_database_files()

    def apply_default_folders(self):
        """The default folders of the settings, offered at start."""
        settings = self.services.settings
        self.set_db_folder(settings.default_folder("database"))
        logs = settings.default_folder("logs")
        if logs and os.path.isdir(logs):
            self.logs_folder_display.setText(logs)

    def register_session_fields(self, fields):
        """The entries of this tab that are remembered between sessions (a folder before the file it lists)."""
        fields.register("data/db_folder", self.db_folder_display.text, self.set_db_folder)
        fields.register("data/sample_name", self.sample_name_input.text, self.sample_name_input.setText)
        fields.register("data/db_file", lambda: self.db_file_combo.currentData() or "", self._select_db_file)
        fields.register("data/logs_folder", self.logs_folder_display.text, self.logs_folder_display.setText)

    def _select_db_file(self, name):
        index = self.db_file_combo.findData(name) if name else -1
        if index >= 0:
            self.db_file_combo.setCurrentIndex(index)

    # ----- logs -----
    def start_logging(self):
        """Start the QCoDeS logger with its log file in the logs folder."""
        log_path = self.logs_folder_display.text().strip()
        if not log_path:
            self.logs_error_display.setText("Select a logs folder first.")
            return
        if not os.path.isdir(log_path):
            self.logs_error_display.setText("Logs path is not a directory.")
            return
        try:
            path = start_file_logging(log_path)
            self.logs_error_display.setText("")
            self.services.status.show(f"Logging to {path}", 5000)
        except Exception as e:
            self.logs_error_display.setText(str(e))
            self.services.status.show(f"Logging error: {e}", 3000)

    def view_logs(self):
        """Open the log explorer on the QCoDeS logs of the logs folder."""
        folder = self.logs_folder_display.text().strip()
        if not folder or not os.path.isdir(folder):
            self.logs_error_display.setText("Select a logs folder first.")
            return
        self.logs_error_display.setText("")
        if self._log_viewer is not None:
            self._log_viewer.close()
        self._log_viewer = LogViewerDialog(self.tab.window(), folder, list(self.services.station.instruments()))
        self._log_viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._log_viewer.destroyed.connect(lambda: setattr(self, "_log_viewer", None))
        self._log_viewer.show()  # not modal: the logs can be read while working

    # ----- reactions to the services -----
    def _on_run_finished(self, session):
        """The run may have created the database / experiment: show it in the explorer."""
        self.show_experiment(session.db_file, session.experiment_name)

    def _on_repetition_finished(self, index, total):
        """Each repetition is a run of its own: it shows in the explorer as soon as it is written, not only at the end
        of them all (the last one is shown when the measurement ends)."""
        session = self.services.run.session
        if session is not None and index < total:
            self.show_experiment(session.db_file, session.experiment_name)

    def _on_database_chosen(self, path):
        """A run needs a database that is not the selected one (a new one, or the next of a full one): create it
        and select it, so that the database in use is always the selected one."""
        try:
            if not os.path.exists(path):
                create_database(path)
        except Exception as e:
            self.services.status.show(f"Cannot create the database {os.path.basename(path)}: {e}", 6000)
            return
        self.populate_database_files(preferred=os.path.basename(path))

    def _on_sample_set_from_outside(self, name):
        if self.sample_name_input.text() != name:
            self.sample_name_input.setText(name)

    # ----- database files -----
    last_note = ""

    def populate_database_files(self, preferred=None):
        """Fill the file selector with the databases of the folder and select ``preferred`` (a file name) or, by
        default, the latest database of the sample, or "a new database" when the sample has none."""
        folder = self.db_folder_display.text().strip()
        combo = self.db_file_combo
        combo.blockSignals(True)
        combo.clear()
        for name in list_db_files(folder):
            combo.addItem(name, name)
        combo.addItem("", None)  # "a new database": its text shows the name it will get
        combo.blockSignals(False)
        self._update_new_item_text()
        target = preferred
        if target is None:
            latest = latest_database(folder, sample_prefix(self.sample_name_input.text())) if folder else None
            target = os.path.basename(latest) if latest else None
        index = combo.findData(target) if target else -1
        combo.setCurrentIndex(index if index >= 0 else combo.count() - 1)
        self.on_db_file_changed()

    def _update_new_item_text(self):
        """The last entry of the file selector: "New database (<name it will get>)"."""
        folder = self.db_folder_display.text().strip()
        prefix = sample_prefix(self.sample_name_input.text())
        combo = self.db_file_combo
        last = combo.count() - 1
        if last < 0 or combo.itemData(last) is not None:
            return
        if prefix and folder:
            combo.setItemText(last, f"New database ({os.path.basename(next_database(folder, prefix))})")
        else:
            combo.setItemText(last, "New database (enter a sample name)")

    def on_sample_changed(self):
        """The databases follow the sample: select its latest one, or a new one."""
        self._publish()
        if self.db_folder_display.text().strip():
            self.populate_database_files()

    def _update_size_label(self):
        path = self.current_db_path()
        label = self.db_size_label
        if path is None:
            label.setText("a new database is created when a run starts")
            label.setStyleSheet("")
            return
        size = size_bytes(path)
        if size > DB_LIMIT_BYTES:
            label.setText(f"{megabytes(size)}: the next run starts a new database")
            label.setStyleSheet("color: #c60;")
        else:
            label.setText(f"{megabytes(size)}")
            label.setStyleSheet("")

    def upgrade_database(self):
        """Create the next database of the series now and select it, whatever the size of the current one."""
        status = self.services.status
        folder = self.db_folder_display.text().strip()
        if not folder:
            status.show("Select a database folder first.", 4000)
            return
        if self.services.gateway.run_active():
            status.show("Wait for the running measurement to finish.", 4000)
            return
        try:
            selected = self._selected_db_file()
            prefix = (prefix_of(selected) if selected else None) or sample_prefix(self.sample_name_input.text())
            if not prefix:
                raise ValueError("Enter a sample name: databases are named after it.")
            path = next_database(folder, prefix)
            create_database(path)
        except Exception as e:
            status.show(f"Cannot create the database: {e}", 6000)
            return
        self.populate_database_files(preferred=os.path.basename(path))
        status.show(f"New database {os.path.basename(path)} created and selected.", 5000)

    def show_experiment(self, db_path, exp_name):
        """Re-read the selected database and show its experiment ``exp_name`` (the explorer after a run).

        The run table is refreshed. If the experiment shown already was this one, the run the user had selected
        stays selected; otherwise the newest run is selected, which is the one that has just been written."""
        previous_experiment, previous_run = self.experiment_combo.currentText(), self.selected_run_id()
        if previous_run is not None and previous_run == self._followed_run:
            previous_run = None  # the user did not choose it: it was the newest run, now there is a newer one
        self.populate_database_files(preferred=os.path.basename(db_path))
        combo = self.experiment_combo
        for i in range(combo.count()):
            if combo.itemText(i).startswith(f"{exp_name},") or combo.itemText(i).startswith(f"{exp_name} ("):
                combo.setCurrentIndex(i)
                same_experiment = previous_experiment.split(" (")[0] == combo.itemText(i).split(" (")[0]
                self._select_run(previous_run if same_experiment else None)
                break

    def _select_run(self, run_id=None):
        """Select the run ``run_id`` in the run table, or the newest run when it is None or no longer there."""
        table = self.runs_table
        rows = [r for r in range(table.rowCount())]
        if not rows:
            return
        wanted = next((r for r in rows if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == run_id), rows[-1]) \
            if run_id is not None else rows[-1]
        table.selectRow(wanted)
        # remember when it is the newest run that was selected, not a run the user chose
        self._followed_run = table.item(wanted, 0).data(Qt.ItemDataRole.UserRole) if wanted == rows[-1] else None
        table.scrollToItem(table.item(wanted, 0))

    def _show_explorer_message(self, text):
        label = self.explorer_message
        label.setText(text)
        label.setStyleSheet("color: #c00;" if text.startswith("Cannot") else "")
        label.setVisible(bool(text))

    def refresh_experiments(self):
        """Fill the experiment selector from the selected database (cleared if there is none)."""
        combo = self.experiment_combo
        combo.blockSignals(True)
        combo.clear()
        combo.blockSignals(False)
        self.runs_table.setRowCount(0)
        self._show_explorer_message("")

        db_path = self.current_db_path()
        if db_path is None:
            return
        try:
            experiments = list_experiments(db_path)
        except Exception as e:
            self._show_explorer_message(
                f"Cannot read database ({describe_error(e)}). It may not be a QCoDeS database, "
                "or it was created by an older QCoDeS version."
            )
            return
        if not experiments:
            self._show_explorer_message("This database contains no experiments.")
            return
        combo.blockSignals(True)
        for exp in experiments:
            sample = f", sample: {exp['sample_name']}" if exp["sample_name"] else ""
            combo.addItem(f"{exp['name']}{sample} ({exp['n_runs']} runs)", exp["exp_id"])
        combo.setCurrentIndex(-1)
        combo.blockSignals(False)

    def selected_run_id(self):
        """run id of the run selected in the explorer, or None."""
        rows = self.runs_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.runs_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def on_run_selected(self):
        shown = self.selected_run_id() is not None
        self.load_snapshot_button.setEnabled(shown)
        self.compare_button.setEnabled(shown)

    def on_experiment_changed(self):
        """List the runs of the selected experiment."""
        table = self.runs_table
        table.setRowCount(0)
        self._show_explorer_message("")
        exp_id = self.experiment_combo.currentData()
        db_path = self.current_db_path()
        if exp_id is None or db_path is None:
            return
        try:
            runs = list_runs(db_path, exp_id)
        except Exception as e:
            self._show_explorer_message(f"Cannot read runs: {describe_error(e)}")
            return
        if not runs:
            self._show_explorer_message("This experiment has no runs.")
            return
        table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            fill_run_row(table, row, run)  # the tag is a dot before the name, the notes are its tooltip

    def on_db_file_changed(self):
        """A database file was selected: show its size and its experiments."""
        self._publish()
        self._update_size_label()
        self.refresh_experiments()
