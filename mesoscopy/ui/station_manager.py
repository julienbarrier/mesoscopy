"""Station and instrument management (UI adapter)."""
import os
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from mesoscopy.core.experiment_parameters import ParameterRegistry, instruments_of
from mesoscopy.core.gateway import USER, parameter_instruments
from mesoscopy.core.station_handover import plan_handover
from mesoscopy.instrument.station_config import read_station_config, root_parameter_names
from mesoscopy.ui.tabs.instrument_status import (
    InstrumentHealthMonitor, ROLE_ERROR, ROLE_IDN, ROLE_OK, ROLE_TIME,
)
from mesoscopy.instrument.station_loader import (
    disconnect_instrument, get_instruments_from_yaml, load_station_from_config,
)


def _update_snapshots(instruments):
    """Worker-thread task: read every parameter of the instruments ({name: instrument}) again."""
    updated, errors = [], []
    for name, instrument in instruments.items():
        try:
            instrument.snapshot(update="All")  # QCoDeS: every parameter is read and its cache refreshed
            updated.append(name)
        except Exception as e:
            errors.append(f"{name}: {e}")
    return updated, errors


class _SnapshotUpdater(QObject):
    """Runs the snapshot update through the instrument gateway (it reads every parameter, which can be slow)
    and reports in the GUI thread."""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.busy = False

    def start(self, instruments):
        """Returns False (with the reason in the gateway) when the instruments are in use."""
        job = self.manager.services.gateway.submit(
            _update_snapshots, instruments, kind=USER, instruments=set(instruments),
            label=f"Updating the snapshot of {', '.join(instruments)}",
        )
        if job is None:
            return False
        self.busy = True
        job.signals.result.connect(self._done)
        job.signals.error.connect(lambda err: self._done(([], [str(err[1])])))
        return True

    def _done(self, result):
        updated, errors = result
        self.busy = False
        manager = self.manager
        manager._set_connected_error("\n".join(errors))
        manager.services.status.show(
            f"Snapshot updated for {', '.join(updated)}." if updated else "No snapshot was updated.", 5000
        )


class StationManager:
    """Loads stations and instruments for the Instruments tab (which owns the widgets it fills).

    The station itself lives in ``services.station``: after a station is loaded, or instruments are connected or
    disconnected, this manager tells the other tabs through that service's signals.
    """

    def __init__(self, tab, services):
        self.tab = tab
        self.services = services
        # health checks (get_idn) go through the instrument gateway as background jobs
        self.health = InstrumentHealthMonitor(
            tab,
            get_components=lambda: instruments_of(self.station),
            gateway=services.gateway,
        )
        self.health.changed.connect(self.refresh_connected_status)
        self.services.station.instrumentsAlive.connect(self.health.note_alive)  # a read of the Monitor counts as a check
        self._snapshot_updater = _SnapshotUpdater(self)

    @property
    def station(self):
        return self.services.station.station

    @property
    def station_file(self):
        return self.services.station.station_file

    def _set_station_error(self, message):
        """Set or clear the station error message in the UI."""
        label = getattr(self.tab, "station_error_display", None)
        if label is not None:
            label.setText(message or "")

    def populate_station_files(self):
        """Populate the station file dropdown with .station.yaml files from the selected folder."""
        self.tab.station_file_combo.clear()
        self._set_station_error("")

        folder = self.tab.station_folder_display.text().strip()
        if not folder:
            self._set_station_error("Select a station folder first.")
            return
        if not os.path.isdir(folder):
            self._set_station_error("Selected path is not a directory.")
            return

        station_files = [f for f in os.listdir(folder) if f.endswith('.station.yaml')]
        station_files.sort()

        if station_files:
            self.tab.station_file_combo.addItems(station_files)
            if len(station_files) == 1:
                self.tab.station_file_combo.setCurrentIndex(0)
        else:
            self._set_station_error("No .station.yaml files found in folder.")

    def load_station(self):
        """Load station from YAML configuration file."""
        self._set_station_error("")
        try:
            config_file = self.tab.station_file_combo.currentText()
            if not config_file:
                self._set_station_error("Please select a station file.")
                self.services.status.show("Please select a station file.", 2000)
                return False

            folder = self.tab.station_folder_display.text()
            if folder:
                config_file = os.path.join(folder, config_file)

            config_file = os.path.abspath(config_file)
            station_config = read_station_config(config_file)
            old_station = self.station
            keep, drop = plan_handover(
                instruments_of(old_station), self.services.registry.station_config, station_config
            )
            gateway = self.services.gateway
            if gateway.run_active():
                self._set_station_error("A measurement is running: a station cannot be loaded now.")
                return False
            if drop and not self._free_to_close(drop):  # nothing has changed yet: the old station stays
                self._set_station_error(self.tab.connected_error_display.text())
                return False

            if drop:  # the parameters of the instruments that are not needed any more go to 0 before they are closed
                handover_ramp_problems = self._ramp_before_closing(drop, why="closing instruments")
            else:
                handover_ramp_problems = []
            remembered = self.services.settings.last_instruments(config_file)  # before anything changes them
            new_station = load_station_from_config(config_file)
            self.services.station.set_station(new_station, config_file, announce=False)
            handover_errors = self._hand_over(old_station, keep, drop)
            self.services.settings.last_station = config_file
            problems = self._load_root_parameters(station_config)
            self.services.registry.attach(
                self.station, ParameterRegistry.path_for_station_file(config_file), station_config
            )
            self.tab.connected_widget.setVisible(True)
            self.populate_connected_instruments(remember=False)  # the memory of this station is used just below
            self.services.status.show(
                "Station loaded successfully." + (f" Disconnected {', '.join(drop)}: not in the new station." if drop else ""),
                6000 if drop else 2000,
            )
            loaded = set(instruments_of(self.station))
            self.populate_instrument_list(config_file, preselect=[n for n in remembered if n not in loaded])
            if self.tab.instr_list.count() == 0:
                self._set_station_error("Station contains no instruments.")
            self.services.station.announce_station()  # the other tabs follow the new station
            self.services.station.notify_instruments_changed()
            problems += handover_errors + handover_ramp_problems
            if problems:
                self._set_station_error("\n".join(problems))
            return True
        except Exception as e:
            msg = str(e)
            self._set_station_error(msg)
            self.services.status.show(f"Error loading station: {e}")
            return False

    def _hand_over(self, old_station, keep, drop):
        """Move the instruments the new station needs into it (they stay connected) and disconnect the others.

        Returns the problems met while closing the others."""
        problems = []
        for name in keep:
            self.station.add_component(old_station.components[name], update_snapshot=False)
        for name in drop:
            try:
                _, step_errors = disconnect_instrument(old_station, name)
                problems += step_errors
            except Exception as e:
                problems.append(f"{name}: {e}")
        for name in drop:
            self.health.forget(name)
        return problems

    def _load_root_parameters(self, station_config):
        """Create the parameters the station file declares at the root (no instrument is needed for them).

        Returns the problems found, one message per parameter that could not be created.
        """
        problems = []
        for name in root_parameter_names(station_config):
            try:
                self.station.load_instrument(name)
            except Exception as e:
                problems.append(f"{name}: {e}")
                print(f"Error loading parameter {name}: {e}")
        return problems

    def populate_instrument_list(self, config_file=None, preselect=()):
        """Populate instrument list from station or YAML config file; the names in ``preselect`` are selected
        (the ones that were loaded the last time this station was used)."""
        self.tab.instr_list.clear()
        instr_names = []

        if config_file:
            instr_names = get_instruments_from_yaml(config_file)
        elif self.station and hasattr(self.station, 'config') and self.station.config:
            if hasattr(self.station.config, 'instrument_configs'):
                instr_names = list(self.station.config.instrument_configs.keys())
            elif hasattr(self.station.config, 'instruments'):
                instr_names = list(self.station.config.instruments.keys())

        for name in sorted(instr_names):
            item = QListWidgetItem(name)
            self.tab.instr_list.addItem(item)
            item.setSelected(name in preselect)  # selecting an item before it is in the list has no effect

        if instr_names:
            self.tab.load_instr_button.setEnabled(True)

    def _discard_failed_instrument(self, name):
        """Forget an instrument whose loading failed half-way.

        QCoDeS applies the presets of the station file while loading. If one fails, the instrument stays
        registered although it is not in the station, and loading it again would fail with "Another
        instrument has the name". Closing it here lets the user fix the station file and retry.
        """
        try:
            disconnect_instrument(self.station, name)
        except Exception as e:
            print(f"Could not clean up {name} after the failed load: {e}")

    def load_selected_instruments(self):
        """Load the selected instruments from the station. Their presets and aliases are applied by QCoDeS while loading."""
        err_label = getattr(self.tab, "instr_error_display", None)
        if err_label is not None:
            err_label.setText("")
        if not self.station:
            if err_label:
                err_label.setText("Load a station first.")
            return False

        names = [item.text() for item in self.tab.instr_list.selectedItems()]
        errors, success_count = self.load_instruments(names)
        if err_label:
            err_label.setText("\n".join(errors))
        return success_count > 0

    def load_instruments(self, names):
        """Load the named instruments of the station, then refresh everything that depends on them.

        Returns (errors, number loaded); an instrument that fails is discarded, see ``_discard_failed_instrument``.
        """
        if self.services.gateway.run_active():  # new instruments would change the parameters under the run
            return ["Instruments cannot be loaded while a measurement runs."], 0
        errors = []
        success_count = 0
        for name in names:
            try:
                self.services.status.show(f"Loading {name}...")
                QApplication.processEvents()
                self.station.load_instrument(name)
                success_count += 1
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"Error loading {name}: {e}")
                self._discard_failed_instrument(name)

        self.services.status.show(f"Loaded {success_count} instruments.", 3000)
        self.populate_connected_instruments()
        if success_count > 0:
            self.services.station.notify_instruments_changed()
        return errors, success_count

    def add_instrument_names(self, names):
        """Offer instruments that are now loadable (e.g. described by a past run) in the "Instruments to Load" list."""
        existing = {self.tab.instr_list.item(i).text() for i in range(self.tab.instr_list.count())}
        for name in sorted(set(names) - existing):
            self.tab.instr_list.addItem(QListWidgetItem(name))
        if names:
            self.tab.load_instr_button.setEnabled(True)

    def _set_connected_error(self, message):
        """Show an error under the connected-instruments buttons; the label is hidden when empty."""
        label = getattr(self.tab, "connected_error_display", None)
        if label is not None:
            label.setText(message or "")
            label.setVisible(bool(message))

    def _free_to_close(self, names):
        """True if the instruments can be closed now: nobody is using them. A short periodic read still under
        way is waited for; a measurement or a user action is not interrupted, the user is told instead."""
        gateway = self.services.gateway
        if gateway.busy(names):
            self._set_connected_error(gateway.reason(names))
            return False
        if not gateway.wait_until_free(names):
            self._set_connected_error("An instrument is not answering: try again in a moment.")
            return False
        return True

    def _ramp_before_closing(self, names=None, why="disconnecting"):
        """Bring the experiment parameters of the instruments about to be closed to 0, and wait for it. Only the ones the
        application has changed (and that are not at 0): there is no reason to ramp the others.

        An instrument that does not answer (the health check says so) is left out: nothing can be set on it, and
        waiting for it would only block the window. Returns the problems met (for the error label)."""
        def answers(parameter):
            return all(self.health.status.get(n, {}).get("ok") is not False for n in parameter_instruments(parameter))

        parameters = [p for p in self.services.ramp.settable_parameters(names, changed_only=True) if answers(p)]
        if not parameters:
            return []
        problems = self.services.ramp.ramp_and_wait(
            parameters, parent=self.tab.tab.window(), title=f"Ramping to 0 before {why}"
        )
        return [f"ramp to 0: {p}" for p in problems]

    def disconnect_selected_instruments(self):
        """Close the selected instruments and remove them from the station."""
        return self.disconnect_instruments([item.text() for item in self.tab.connected_instr_list.selectedItems()])

    def disconnect_instruments(self, names):
        """Close the named instruments and remove them from the station."""
        self._set_connected_error("")
        if not self.station:
            self._set_connected_error("Load a station first.")
            return False

        if not self._free_to_close(names):
            return False
        errors = self._ramp_before_closing(names)  # the parameters of these instruments go to 0 first
        closed_count = 0
        for name in names:
            try:
                self.services.status.show(f"Disconnecting {name}...")
                QApplication.processEvents()
                found, step_errors = disconnect_instrument(self.station, name)
                if found:
                    closed_count += 1
                errors.extend(step_errors)
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"Error disconnecting {name}: {e}")

        if errors:
            self._set_connected_error("\n".join(errors))

        self.services.status.show(f"Disconnected {closed_count} instruments.", 3000)

        self.populate_connected_instruments()

        if closed_count > 0:
            self.services.station.notify_instruments_changed()

        return closed_count > 0

    def update_selected_snapshots(self):
        """Update the snapshot of the instruments selected in the connected list."""
        self.update_snapshots([item.text() for item in self.tab.connected_instr_list.selectedItems()])

    def update_snapshots(self, names):
        """Read every parameter of the named instruments again (``snapshot(update="All")``).

        QCoDeS keeps the last known value of each parameter and the snapshot stored with a run uses
        them; this brings them up to date with changes made outside the application (front panel,
        another program).
        """
        self._set_connected_error("")
        status = self.services.status
        if not self.station:
            self._set_connected_error("Load a station first.")
            return
        if not names:
            self._set_connected_error("Select the instruments to update.")
            return
        if self._snapshot_updater.busy:
            status.show("A snapshot update is already running.", 3000)
            return
        instruments = {n: i for n, i in instruments_of(self.station).items() if n in names}
        status.show(f"Updating the snapshot of {', '.join(instruments)}...")
        if not self._snapshot_updater.start(instruments):
            status.show(self.services.gateway.last_refusal, 5000)

    def populate_connected_instruments(self, remember=True):
        """List all components of the loaded station in the "Connected instruments" list.

        The names are remembered for the station file (``remember``): they are pre-selected the next time it is
        loaded."""
        lst = self.tab.connected_instr_list
        lst.clear()
        names = sorted(instruments_of(self.station))
        lst.addItems(names)
        if remember and self.station_file:
            self.services.settings.set_last_instruments(self.station_file, names)
        self.health.sync()
        self.refresh_connected_status()
        self.tab.disconnect_instr_button.setEnabled(bool(names))
        self.tab.update_snapshot_button.setEnabled(bool(names))

    def refresh_connected_status(self):
        """Copy identity/health information from the monitor onto the connected-list items."""
        lst = getattr(self.tab, "connected_instr_list", None)
        if lst is None:
            return
        for i in range(lst.count()):
            item = lst.item(i)
            status = self.health.status.get(item.text())
            if status:
                item.setData(ROLE_IDN, status["idn"])
                item.setData(ROLE_OK, status["ok"])
                item.setData(ROLE_TIME, status["time"])
                item.setData(ROLE_ERROR, status["error"])
        lst.viewport().update()
        # offer "Reconnect" as soon as one instrument stops responding
        self.tab.reconnect_instr_button.setVisible(
            any(s["ok"] is False for s in self.health.status.values())
        )

    def reconnect_selected_instruments(self):
        """Reload the selected instruments: disconnect them, then load them again from the station config."""
        self._set_connected_error("")
        if not self.station:
            self._set_connected_error("Load a station first.")
            return False
        names = [item.text() for item in self.tab.connected_instr_list.selectedItems()]
        if not names:
            self._set_connected_error("Select the instruments to reconnect.")
            return False

        if not self._free_to_close(names):
            return False
        errors = self._ramp_before_closing(names, why="reconnecting")
        reloaded = []
        for name in names:
            try:
                self.services.status.show(f"Reconnecting {name}...")
                QApplication.processEvents()
                _, step_errors = disconnect_instrument(self.station, name)
                errors.extend(step_errors)  # problems while closing are not fatal
                self.health.forget(name)
                self.station.load_instrument(name)
                reloaded.append(name)
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"Error reconnecting {name}: {e}")
                self._discard_failed_instrument(name)

        if errors:
            self._set_connected_error("\n".join(errors))
        self.services.status.show(f"Reconnected {len(reloaded)} instruments.", 3000)

        # instruments that were not reloaded are dropped from the configuration boxes
        self.populate_connected_instruments()
        self.services.station.notify_instruments_changed()
        return bool(reloaded)

    def disconnect_all_instruments(self):
        """Disconnect every instrument loaded in the station (no UI refresh, used on shutdown)."""
        self.health.stop()
        if not self.station:
            return
        for problem in self._ramp_before_closing(None, why="closing"):  # every parameter goes to 0 first
            print(f"Error: {problem}")
        for name in list(instruments_of(self.station)):
            try:
                _, step_errors = disconnect_instrument(self.station, name)
                for err in step_errors:
                    print(f"Error disconnecting {err}")
            except Exception as e:
                print(f"Error disconnecting {name}: {e}")
