"""Load Snapshot: set the application up as it was for a past run (UI adapter, logic in core.snapshot_restore)."""
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog, QWidget
from qcodes.utils import NumpyJSONEncoder

from mesoscopy.core.snapshot_restore import (
    add_stored_entries, apply_definitions, apply_values, definitions_to_restore, plan_definitions,
    plan_instruments, plan_values, read_run, setup_for, value_routes,
)
from mesoscopy.core.gateway import USER, parameter_instruments
from mesoscopy.ui.tabs.run_picker_dialog import RunPickerDialog
from mesoscopy.ui.tabs.snapshot_dialog import SnapshotDialog

MAX_PROBLEMS_SHOWN = 25
STATE_FILE_KEY = "mesoscopy_instrument_state"
STATE_FILE_VERSION = 1


@dataclass
class LoaderHooks:
    """What the loader needs from the rest of the application, given by the main window (the loader knows no tab)."""
    parent: QWidget                                  # parent of the dialogs
    instrument_manager: object                       # StationManager: load_instruments, add_instrument_names
    apply_sweep_state: Callable[[dict], list]        # set the Measurement tab up; returns the problems found
    show_measurement_tab: Callable[[], None]


class SnapshotLoader(QObject):
    """Connects the instruments of a run, creates its experiment parameters, sets its instrument values and
    fills the Measurement tab. Nothing is run. Every change that touches an instrument is confirmed first.

    It is started by signals of the tabs (the Data tab's "Load Snapshot", the Instruments tab's right-click menu)."""

    def __init__(self, services, hooks):
        super().__init__()  # a QObject: results of the worker thread are delivered in the GUI thread
        self.services = services
        self.hooks = hooks
        self._context = None
        self._progress = None
        self._last_directory = ""

    def load(self, db_path, run_id):
        status, gateway, parent = self.services.status, self.services.gateway, self.hooks.parent
        if self._context is not None:
            status.show("A snapshot is being loaded.", 3000)
            return
        if gateway.run_active():
            status.show("Wait for the running measurement to finish.", 4000)
            return
        if self.services.station.station is None:
            status.show("Load a station first (Instruments tab).", 4000)
            return
        try:
            record = read_run(db_path, run_id)
        except Exception as e:
            QMessageBox.warning(parent, "Load snapshot", f"Cannot read run {run_id}: {e}")
            return

        notes = []
        if record.snapshot is None:
            notes.append("This run has no snapshot: only what its data shows can be set up.")
        if not self._connect_instruments(record, notes):
            return

        registry, station = self.services.registry, self.services.station.station
        setup, problems, how = setup_for(record, registry, station)
        notes += [f"Measurement tab: {p}" for p in problems]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            values = plan_values(station, record.snapshot)
            definitions = plan_definitions(registry, definitions_to_restore(setup)) if setup else []
        finally:
            QApplication.restoreOverrideCursor()

        sample = f", sample {record.sample}" if record.sample else ""
        summary = (f"Run {record.run_id} \"{record.measurement}\" of experiment \"{record.experiment}\"{sample} "
                   f"({'completed' if record.completed else 'not completed'}).\n"
                   f"Setup of the Measurement tab: {how or 'not available'}.")
        dialog = SnapshotDialog(parent, summary, values, definitions, setup is not None, notes)
        if not dialog.exec():
            status.show("Load snapshot cancelled.", 3000)
            return

        problems = apply_definitions(registry, dialog.definition_changes())  # the registry tells the tabs
        self._context = {"label": f"run {record.run_id}", "record": record,
                         "setup": setup if dialog.wants_setup() else None, "problems": problems}
        chosen = dialog.selected_values()
        if chosen:
            self._start_values(chosen, value_routes(registry))
        else:
            self._finish()

    # ----- step 1: instruments -----
    def _connect_instruments(self, record, notes):
        """Offer to connect the instruments of the run that are not loaded. False if the user cancelled."""
        window, registry = self.hooks.parent, self.services.registry
        plans = plan_instruments(self.services.station.station, registry.station_config, record.snapshot)
        loadable = [p for p in plans if p.source]
        notes += [f"{p.name} cannot be connected: it is not described in the station file or in the run."
                  for p in plans if not p.source]
        if not loadable:
            return True
        box = QMessageBox(window)
        box.setWindowTitle("Load snapshot")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("The run used instruments that are not connected. Connect them?")
        box.setInformativeText("\n".join(p.describe() for p in loadable))
        connect = box.addButton("Connect them", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Skip them", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is cancel:
            return False
        if box.clickedButton() is connect:
            manager = self.hooks.instrument_manager
            registry.station_config = add_stored_entries(self.services.station.station, registry.station_config, loadable)
            manager.add_instrument_names([p.name for p in loadable])
            errors, _ = manager.load_instruments([p.name for p in loadable])
            notes += [f"Could not connect {e}" for e in errors]
        else:
            notes += [f"{p.name} is not connected: its values are not restored." for p in loadable]
        return True

    # ----- step 3: values, in a worker thread (a ramp can take a while) -----
    def _start_values(self, changes, routes):
        instruments = set().union(*(parameter_instruments(c.parameter) for c in changes))
        job = self.services.gateway.submit(
            apply_values, changes, routes, kind=USER, instruments=instruments,
            label=f"Setting {len(changes)} instrument parameter(s)",
        )
        if job is None:  # the instruments are in use: nothing was set
            self._context["problems"].append(f"the instrument values were not set: {self.services.gateway.last_refusal}")
            self._finish()
            return
        self._progress = QProgressDialog(f"Setting {len(changes)} instrument parameter(s)...", None, 0, 0,
                                         self.hooks.parent)
        self._progress.setWindowTitle("Load snapshot")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.show()
        job.signals.result.connect(self._values_set)
        job.signals.error.connect(self._values_failed)
        job.signals.finished.connect(self._values_finished)

    def _values_set(self, result):
        done, problems = result
        self._context["values_set"] = done
        self._context["problems"] += problems

    def _values_failed(self, error):
        self._context["problems"].append(f"setting the instrument values: {error[1]}")

    def _values_finished(self):
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._finish()

    # ----- step 4: the Measurement tab -----
    def _finish(self):
        context, self._context = self._context, None
        record, setup, problems = context["record"], context["setup"], context["problems"]
        if setup is not None:
            sweep = dict(setup["sweep"], experiment_name=record.experiment, measurement_name=record.measurement)
            problems += self.hooks.apply_sweep_state(sweep)
            if record.sample:
                self.services.data.set_sample_name(record.sample)
            self.hooks.show_measurement_tab()
        message = f"State from {context['label']} loaded: {context.get('values_set', 0)} value(s) set"
        if setup is not None:
            message += ", Measurement tab set up (nothing was run)"
        self.services.status.show(message + ".", 8000)
        self._report(problems)

    def _report(self, problems):
        if problems:
            shown = problems[:MAX_PROBLEMS_SHOWN]
            if len(problems) > len(shown):
                shown.append(f"... and {len(problems) - len(shown)} more")
            QMessageBox.warning(self.hooks.parent, "Load snapshot",
                                "Some things could not be restored:\n\n" + "\n".join(shown))

    # ================= the state of one instrument: save, restore from a file, restore from a run =================
    def _ready_for_instrument(self, name):
        """The instrument ``name`` if the application can work on it now (station loaded, no run going), else None."""
        status, gateway = self.services.status, self.services.gateway
        instruments = self.services.station.instruments()
        if self._context is not None:
            status.show("A snapshot is being loaded.", 3000)
        elif gateway.busy({name}):
            status.show(gateway.reason({name}), 4000)
        elif name not in instruments:
            status.show(f"{name} is not connected.", 4000)
        else:
            return instruments[name]
        return None

    def _start_directory(self):
        return self._last_directory or self.services.data.folder or os.path.expanduser("~")

    def save_instrument_state(self, name):
        """Update the snapshot of the instrument (reads all its parameters), then save it as a JSON file."""
        instrument = self._ready_for_instrument(name)
        if instrument is None:
            return
        self.services.status.show(f"Reading all the parameters of {name}...")
        job = self.services.gateway.submit(
            lambda: instrument.snapshot(update="All"), kind=USER, instruments={name},
            label=f"Reading all the parameters of {name}",
        )
        if job is None:
            self.services.status.show(self.services.gateway.last_refusal, 5000)
            return
        job.signals.result.connect(lambda snapshot: self._write_state(name, snapshot))
        job.signals.error.connect(lambda error: QMessageBox.warning(
            self.hooks.parent, "Save instrument state", f"Could not read {name}: {error[1]}"))

    def _write_state(self, name, snapshot):
        window = self.hooks.parent
        path, _ = QFileDialog.getSaveFileName(
            window, f"Save the state of {name}", os.path.join(self._start_directory(), f"{name}_state.json"),
            "JSON (*.json)")
        if not path:
            self.services.status.show("Save cancelled.", 3000)
            return
        if not path.endswith(".json"):
            path += ".json"
        definitions = [d.to_dict() for d in self.services.registry.definitions.values()
                       if d.kind == "instrument" and d.source and d.source[0] == name]
        payload = {STATE_FILE_KEY: STATE_FILE_VERSION, "instrument": name,
                   "saved": datetime.now().isoformat(timespec="seconds"),
                   "snapshot": snapshot, "experiment_parameters": definitions}
        try:
            with open(path, "w") as f:
                json.dump(payload, f, cls=NumpyJSONEncoder, indent=2)
        except OSError as e:
            QMessageBox.warning(window, "Save instrument state", f"Could not write {path}: {e}")
            return
        self._last_directory = os.path.dirname(path)
        self.services.status.show(f"State of {name} saved to {path}.", 6000)

    def restore_instrument_from_file(self, name):
        """Pick a JSON file written by "Save state" and restore the instrument and its experiment parameters."""
        if self._ready_for_instrument(name) is None:
            return
        window = self.hooks.parent
        path, _ = QFileDialog.getOpenFileName(window, f"Restore the state of {name} from a file",
                                              self._start_directory(), "JSON (*.json)")
        if not path:
            return
        self._last_directory = os.path.dirname(path)
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, dict) or STATE_FILE_KEY not in data or not isinstance(data.get("snapshot"), dict):
                raise ValueError("this is not an instrument state file written by mesoscopy")
        except (OSError, ValueError) as e:
            QMessageBox.warning(window, "Restore instrument state", f"Cannot read {os.path.basename(path)}: {e}")
            return
        saved_name = data.get("instrument", name)
        definitions = [dict(d, source=[name, *d["source"][1:]]) for d in data.get("experiment_parameters", [])
                       if d.get("source")]  # a state saved under another instrument name applies to this one
        notes = []
        if saved_name != name:
            notes.append(f"The file holds the state of {saved_name}: it is applied to {name}.")
        summary = f"State of {saved_name} saved {data.get('saved', '')} in {os.path.basename(path)}, restored on {name}."
        self._restore_instrument(name, data["snapshot"], definitions, summary, notes, f"file {os.path.basename(path)}")

    def restore_instrument_from_run(self, name):
        """Pick a run in a pop-up and restore the instrument and its experiment parameters as they were then."""
        if self._ready_for_instrument(name) is None:
            return
        window, data = self.hooks.parent, self.services.data
        db_path = data.selected_file  # the database in use: the one selected in the Data tab
        if not db_path or not os.path.isfile(db_path):
            QMessageBox.warning(window, "Restore instrument state",
                                "Select an existing database in the Data tab first: runs are taken from it.")
            return
        picker = RunPickerDialog(window, db_path, title=f"Restore the state of {name} from a run")
        if not picker.exec():
            return
        _, run_id = picker.selection()
        try:
            record = read_run(db_path, run_id)
        except Exception as e:
            QMessageBox.warning(window, "Restore instrument state", f"Cannot read run {run_id}: {e}")
            return
        stored = ((record.snapshot or {}).get("station") or {}).get("instruments") or {}
        if name not in stored:
            QMessageBox.warning(window, "Restore instrument state",
                                f"The snapshot of run {record.run_id} holds no instrument named {name}"
                                + (f" (it has: {', '.join(stored)})." if stored else " (it has no snapshot)."))
            return
        definitions = [d for d in (record.setup or {}).get("experiment_parameters", [])
                       if d.get("kind") == "instrument" and d.get("source") and d["source"][0] == name]
        summary = (f"Run {record.run_id} \"{record.measurement}\" of experiment \"{record.experiment}\" "
                   f"in {os.path.basename(db_path)}: state of {name}.")
        self._restore_instrument(name, stored[name], definitions, summary, [], f"run {record.run_id}")

    def _restore_instrument(self, name, instrument_snapshot, definitions, summary, notes, label):
        """Review, then apply the stored state of one instrument and the experiment parameters on it."""
        window, registry = self.hooks.parent, self.services.registry
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            values = plan_values(self.services.station.station, {"station": {"instruments": {name: instrument_snapshot}}}, only=[name])
            changes = plan_definitions(registry, definitions)
        finally:
            QApplication.restoreOverrideCursor()
        dialog = SnapshotDialog(window, summary, values, changes, False, notes,
                                title=f"Restore the state of {name}", show_setup=False)
        if not dialog.exec():
            self.services.status.show("Restore cancelled.", 3000)
            return
        problems = apply_definitions(registry, dialog.definition_changes())  # the registry tells the tabs
        self._context = {"label": label, "record": None, "setup": None, "problems": problems}
        chosen = dialog.selected_values()
        if chosen:
            self._start_values(chosen, value_routes(registry))
        else:
            self._finish()
