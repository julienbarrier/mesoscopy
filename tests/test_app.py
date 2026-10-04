"""The application, tab by tab, on the simulated instruments (see ``conftest.py``).

The tests run in the order of the file and share the window, the station and the database: the runs of the Measurement tests
are what the queue and the explorer tests look at afterwards.
"""
import copy
import os
import time

import numpy as np
import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from qcodes.dataset import load_by_id
from qcodes.dataset.sqlite.database import connect

from helpers import dimension, pump, recipe, wait
from mesoscopy.core import queue_steps
from mesoscopy.core.experiment_parameters import ParameterDefinition
from mesoscopy.core.run_tags import get_run_tags


@pytest.fixture(scope="module")
def parameters(app):
    return app.services.registry.parameters


def show(app, tab):
    app.window.tabs.setCurrentWidget(tab)
    pump(0.2)


def run_recipe(app, state, timeout=90):
    """Set the Measurement tab up from ``state``, press Run, wait for the end. Returns the RunSession."""
    sweep = app.window.sweep_tab
    show(app, app.window.sweep_tab_widget)
    assert sweep.set_state(state) == []
    pump(0.1)
    finished = []
    app.services.run.runFinished.connect(finished.append)
    try:
        sweep.request_run()
        assert wait(lambda: bool(finished), timeout), "the measurement did not finish"
    finally:
        app.services.run.runFinished.disconnect(finished.append)
    pump(0.4)
    return finished[-1]


def written(session):
    """[(run id, completed, number of results)] of the runs a session wrote."""
    conn = connect(session.db_file, read_only=True)
    try:
        return [(i, load_by_id(i, conn=conn).completed, load_by_id(i, conn=conn).number_of_results) for i in session.run_ids]
    finally:
        conn.close()


# ----------------------------------------------------------------------------------------------- station and tabs
def test_tabs_open_as_the_set_up_goes(app):
    window = app.window
    assert [window.tabs.isTabEnabled(i) for i in range(5)] == [True] * 5
    assert not window.tabs.isTabEnabled(5)  # nothing is monitored yet


def test_station_aliases_are_experiment_parameters(app, parameters):
    assert {"dummy_dac_Vtop", "dummy_dac_Vback", "dummy_dmm_signal", "dummy_dmm_signal2"} <= set(parameters())
    definitions = app.services.registry.definitions
    assert (definitions["dummy_dac_Vtop"].min_value, definitions["dummy_dac_Vtop"].max_value) == (-2, 2)
    assert definitions["dummy_dac_Vtop"].max_ramp_rate == pytest.approx(2.0)


def test_the_health_check_sees_the_instruments(app):
    health = app.window.instruments_tab.manager.health
    assert wait(lambda: all(health.status.get(n, {}).get("ok") for n in ("dummy_dac", "dummy_dmm", "dummy_scope")), 20)


def test_instrument_panel_pages(app):
    panel = app.window.instruments_tab.instrument_detail
    app.window.instruments_tab.connected_instr_list.setCurrentRow(0)
    pump(0.2)
    assert panel.name is not None
    for page in range(3):
        panel._show_page(page)
        pump(0.05)


# ------------------------------------------------------------------------------------------------ parameter explorer
def test_explorer_reads_sets_and_restores(app):
    explorer = app.window.parameter_explorer_tab
    show(app, app.window.parameter_explorer_widget)
    explorer.selector.set_path(["dummy_dac"])
    explorer.recursive_checkbox.setChecked(True)
    pump(0.3)
    assert explorer.table.rowCount() >= 5
    explorer.read_all()
    assert wait(lambda: not app.services.gateway.busy(), 15)
    gate = app.services.station.instruments()["dummy_dac"].ch1
    explorer.set_parameter(gate, "0.5")
    assert wait(lambda: abs(gate() - 0.5) < 1e-9, 10)
    explorer.set_parameter(gate, "99")  # beyond the validator: refused before it reaches the instrument
    pump(0.2)
    assert gate() == pytest.approx(0.5)
    explorer.restore_previous_value(gate)
    assert wait(lambda: abs(gate()) < 1e-9, 10)


def test_experiment_parameters_can_be_made_edited_and_removed(app, parameters):
    registry = app.services.registry
    registry.add(ParameterDefinition(name="gate3", kind="instrument", source=["dummy_dac", "ch3"], unit="V",
                                     min_value=-1.0, max_value=1.0, max_ramp_rate=2.0))
    gate3 = parameters()["gate3"]
    with pytest.raises(Exception):
        gate3.validate(2.0)
    assert gate3.step is not None and gate3.inter_delay is not None
    registry.add(ParameterDefinition(name="twice", kind="derived", expression="dummy_dmm_signal*2", unit="V"))
    assert isinstance(parameters()["twice"](), float)
    with pytest.raises(ValueError):
        registry.add(ParameterDefinition(name="bad", kind="derived", expression="nonexistent+1"))
    registry.add(ParameterDefinition(name="spectrum", kind="instrument", source=["dummy_scope", "trace"]))
    registry.add(ParameterDefinition(name="spec_user", kind="trace", source=["dummy_scope", "spectrum"], axis_kind="linspace",
                                     axis_start=0, axis_stop=1000, axis_points=64, axis_name="f", axis_unit="Hz"))
    assert {"spectrum", "spec_user"} <= set(parameters())
    registry.update(ParameterDefinition(**{**registry.definitions["gate3"].__dict__, "max_value": 0.8}))
    assert registry.definitions["gate3"].max_value == 0.8
    with pytest.raises(ValueError):
        registry.remove("dummy_dmm_signal")  # "twice" is computed from it
    app.window.parameter_explorer_tab.refresh_experiment_table()
    assert app.window.parameter_explorer_tab.exp_table.rowCount() >= 8


def test_explorer_menus_build(app):
    explorer = app.window.parameter_explorer_tab
    app.shown.menus.clear()
    explorer.table.selectRow(0)
    explorer._show_browser_menu(explorer.table.visualRect(explorer.table.model().index(0, 1)).center())
    explorer.exp_table.selectRow(0)
    explorer._show_experiment_menu(explorer.exp_table.visualRect(explorer.exp_table.model().index(0, 0)).center())
    assert len(app.shown.menus) == 2


# ------------------------------------------------------------------------------------------------ alarms and ramps
def test_alarm_goes_off_near_the_limit(app, parameters):
    vtop = parameters()["dummy_dac_Vtop"]
    added, message = app.services.alarms.add(vtop)
    assert added, message
    assert app.services.alarms._check(vtop, 1.95) is not None
    assert app.services.alarms._check(vtop, 0.5) is None
    app.services.alarms.remove(vtop)


def test_parameters_that_were_changed_are_ramped_to_zero(app, parameters):
    vtop = parameters()["dummy_dac_Vtop"]
    vtop(0.3)
    app.services.restore.mark_touched(vtop)
    ramped = app.services.ramp.settable_parameters(changed_only=True)
    assert vtop in ramped
    assert app.services.ramp.ramp_and_wait(ramped, parent=app.window, title="test") == []
    assert abs(vtop()) < 1e-9


# ------------------------------------------------------------------------------------------------ monitor and its log
def test_monitor_reads_and_logs(app, parameters):
    monitor = app.window.monitor_tab
    for name in ("dummy_dmm_signal", "dummy_dac_Vtop"):
        app.services.station.add_monitored(parameters()[name])
    pump(0.3)
    monitor.poll(background=False)
    assert wait(lambda: not monitor._polling, 15)
    assert sum(1 for r in monitor._rows.values() if r["value"].text() not in ("", "—")) == 2
    monitor._log_started = time.time() - 100
    monitor._log_last = 0.0
    monitor._log_tick()
    logs = [f for f in os.listdir(app.dirs["logs"]) if f.startswith("monitor_")]
    assert logs and any(open(os.path.join(app.dirs["logs"], f)).readline().count("\t") == 2 for f in logs)
    monitor._show_context_menu(monitor.table.visualRect(monitor.table.model().index(0, 0)).center())
    app.services.station.remove_monitored(parameters()["dummy_dac_Vtop"])
    assert len(monitor._monitored()) == 1


# ---------------------------------------------------------------------------------------------- measurements
def test_a_one_dimensional_sweep(app):
    session = run_recipe(app, recipe("m1d", [dimension()]))
    assert not session.failed and not session.stopped
    assert written(session)[0][1:] == (True, 6)
    plot = app.window.sweep_tab.plot_panel
    assert plot._data["n_points"] == 6 and plot._data["completed"]
    assert plot.elapsed_field.text() != "--:--:--"
    assert os.path.basename(session.db_file) == "Test_00.db"


def test_a_snake_map(app):
    state = recipe("m2d", [dimension(num=4), dimension(component="dummy_dac_Vback", start="0", stop="1", num=5)],
                   measured=("dummy_dmm_signal", "dummy_dmm_signal2"), snake=True)
    session = run_recipe(app, state)
    assert not session.failed and written(session)[0][1] is True
    conn = connect(session.db_file, read_only=True)
    values = load_by_id(session.run_ids[0], conn=conn).get_parameter_data()["dummy_dmm_signal"]["dummy_dac_Vback"].ravel()
    conn.close()
    assert list(values[5:10]) == sorted(values[5:10], reverse=True)  # the second pass goes back
    plot = app.window.sweep_tab.plot_panel
    assert not plot._data["single_curve"]


def test_the_other_sweep_classes(app):
    assert not run_recipe(app, recipe("mlog", [dimension(cls="LogSweep", component="dummy_dac_Vback", start="0.1", stop="1", num=5)])).failed
    together = dimension(cls="TogetherSweep", num=5)
    together["together"] = [["dummy_dac_Vtop"], ["dummy_dac_Vback"]]
    together["together_stops"] = ["0.5", "1"]
    assert not run_recipe(app, recipe("mtog", [together])).failed
    array = dimension(cls="ArraySweep", array="np.concatenate((np.linspace(0, 0.4, 4), np.linspace(0.4, 0, 4)))")
    assert written(run_recipe(app, recipe("marr", [array])))[0][2] == 8
    repeated = run_recipe(app, recipe("mrep", [dimension(num=4)], repeat={"enabled": True, "times": 3}, back_and_forth=True))
    assert len(repeated.run_ids) == 3 and all(done for _, done, _ in written(repeated))


def test_traces_with_scalars(app):
    session = run_recipe(app, recipe("mtrace", [dimension(num=4)], measured=("dummy_dmm_signal", "spectrum")))
    assert not session.failed
    plot = app.window.sweep_tab.plot_panel
    assert plot._data["trace_length"] == 64 and not plot._data["single_curve"]
    alone = run_recipe(app, recipe("mtrace2", [], measured=("spec_user",)))
    assert not alone.failed


def test_pause_resume_and_stop(app):
    sweep, run = app.window.sweep_tab, app.services.run
    show(app, app.window.sweep_tab_widget)
    sweep.set_state(recipe("mstop", [dimension(num=40, delay="0.05")]))
    started, finished = [], []
    run.runStarted.connect(started.append)
    run.runFinished.connect(finished.append)
    sweep.request_run()
    assert wait(lambda: bool(started), 10)
    pump(0.4)
    run.toggle_pause()
    assert wait(lambda: run.state == "paused", 10)
    assert run.session.progress.paused  # the clocks stand still
    run.toggle_pause()
    pump(0.3)
    assert run.state == "running"
    run.stop()
    assert wait(lambda: bool(finished), 20)
    pump(0.3)
    run.runStarted.disconnect(started.append)
    run.runFinished.disconnect(finished.append)
    assert finished[-1].stopped and not finished[-1].failed and written(finished[-1])[0][1] is True


def test_a_breakout_condition_ends_the_run(app, parameters):
    registry, sweep = app.services.registry, app.window.sweep_tab
    definition = copy.deepcopy(registry.definitions["dummy_dmm_signal"])
    definition.breakout.enabled, definition.breakout.operator, definition.breakout.threshold = True, ">=", 0.0
    definition.breakout.absolute = True
    registry.update(definition)
    pump(0.1)
    assert sweep.breakout_checkbox.isEnabled()
    session = run_recipe(app, recipe("mbreak", [dimension(num=30, delay="0.01")], breakout=True))
    assert (session.reason or session.stopped) and written(session)[0][2] < 30
    definition.breakout.enabled = False
    registry.update(definition)


def test_ramp_to_zero_when_finished(app, parameters):
    run_recipe(app, recipe("mramp", [dimension(start="0", stop="0.4", num=4)], ramp_to_zero=True))
    assert wait(lambda: not app.services.gateway.busy(), 15)
    assert wait(lambda: abs(parameters()["dummy_dac_Vtop"]()) < 1e-9, 10)


def test_check_setup_refuses_a_sweep_beyond_the_limits(app):
    sweep = app.window.sweep_tab
    show(app, app.window.sweep_tab_widget)
    sweep.set_state(recipe("mlim", [dimension(start="0", stop="10", num=3)]))
    app.shown.dialogs.clear()
    sweep.check_setup()
    assert app.shown.dialogs and "invalid" in str(app.shown.dialogs[-1])
    sweep.request_run()
    assert app.shown.dialogs[-1][0] == "warning" and not app.services.run.running


def test_advanced_options_export_and_save_plots(app):
    out = os.path.join(app.dirs["data"], "exported")
    advanced = {"enter": [{"name": "w", "code": "wait(0.1)\nwait_below(dummy_dmm_signal, 100, timeout=5)", "enabled": True}],
                "exit": [{"name": "x", "code": "dummy_dac_Vtop(0)", "enabled": True}], "setpoints": ["dummy_dmm_signal2"],
                "write_period": 0.2, "use_threads": True, "in_memory_cache": True, "log_info": "test",
                "export": True, "export_type": "csv", "export_path": out, "save_plot": True, "plot_format": "png"}
    axis = dimension(num=4)
    axis["actions"] = [{"name": "p", "code": "time.sleep(0.01)", "enabled": True}]
    axis["get_after_set"] = True
    session = run_recipe(app, recipe("madv", [axis], advanced=advanced))
    assert not session.failed
    files = os.listdir(out)
    assert any(f.endswith(".csv") for f in files) and any(f.endswith(".png") for f in files), files


def test_several_datasets_in_one_measurement(app):
    datasets = {"datasets": [{"name": "a", "setpoints": ["dummy_dac_Vtop"], "measured": ["dummy_dmm_signal"]},
                             {"name": "b", "setpoints": ["dummy_dac_Vtop"], "measured": ["dummy_dmm_signal2"]}]}
    session = run_recipe(app, recipe("mdata", [dimension(num=3)], measured=("dummy_dmm_signal", "dummy_dmm_signal2"),
                                     advanced=datasets))
    assert len(session.run_ids) == 2 and all(done for _, done, _ in written(session))


def test_live_plot_controls_and_picking_values(app):
    sweep, plot = app.window.sweep_tab, app.window.sweep_tab.plot_panel
    run_recipe(app, recipe("mplot", [dimension(num=11)]))
    plot.derivative_button.setChecked(True)
    pump(0.1)
    plot.derivative_button.setChecked(False)
    plot.x_factor.setText("1000")
    pump(0.1)
    plot.x_factor.setText("1")
    plot.past_spin.setValue(3)
    pump(0.2)
    assert len(plot.canvas.axes.lines) >= 1
    box = sweep.dimension_boxes[0]
    box.start_input.setFocus()
    sweep._focus_changed(None, box.start_input)
    pump(0.1)
    assert len(plot.canvas.axes.lines) >= 3  # the curve and the two marker lines
    plot.canvas.clicked.emit(0.2, 0.1)
    assert float(box.start_input.text()) == pytest.approx(0.2)
    plot.canvas.dragged.emit(0.1, 0.4)
    assert (box.start_input.text(), box.stop_input.text()) == ("0.1", "0.4")
    app.shown.menus.clear()
    plot._show_plot_menu(plot.canvas.rect().center())
    menu = app.shown.menus[-1]
    assert len(menu.actions()) >= 6 and hasattr(menu, "tag_picker")  # the extrema, the tag dots and the notes
    menu.tag_picker.tagChosen.emit("green")
    plot._write_notes(plot._run_id, "note from the test")
    assert get_run_tags(plot._db_file, plot._run_id) == ("green", "note from the test")
    sweep._focus_changed(None, box.delay_input)
    assert sweep._pick_target is None


# ------------------------------------------------------------------------------------------------------------ queue
def test_the_queue_runs_measurements_and_steps(app):
    queue, sweep = app.services.queue, app.window.sweep_tab
    show(app, app.window.queue_widget)
    queue.items.clear()
    queue.changed.emit()
    sweep.set_state(recipe("qa", [dimension(num=3)]))
    sweep.add_to_queue()
    queue.insert([queue_steps.new_step("set", parameter="dummy_dac_Vtop", value=0.2),
                  queue_steps.new_step("wait_stable", parameter="dummy_dac_Vtop", use_target=True, value=0.2, tol=0.05,
                                       dwell=0.2, timeout=20)])
    sweep.set_state(recipe("qb", [dimension(num=3, stop="0.3")]))
    sweep.add_to_queue()
    queue.insert([queue_steps.new_step("repeat_until", expression="True", max_repeats=2)])
    assert len(app.window.queue_tab.list.findItems("", __import__("PyQt6.QtCore", fromlist=["x"]).Qt.MatchFlag.MatchContains)) == 5
    assert queue.start()
    assert wait(lambda: not queue.active, 90)
    pump(0.3)
    assert [i.status for i in queue.items] == ["done"] * 5
    assert all(i.run_ids for i in queue.items if not queue_steps.is_step(i.state))


def test_skip_and_stop_end_a_measurement_and_a_wait(app):
    queue, sweep = app.services.queue, app.window.sweep_tab
    queue.items.clear()
    sweep.set_state(recipe("qs", [dimension(num=40, delay="0.05")]))
    sweep.add_to_queue()
    queue.insert([queue_steps.new_step("wait", seconds=30)])
    queue.start()
    assert wait(lambda: queue.current is not None and app.services.run.running, 10)
    pump(0.3)
    queue.skip()
    assert wait(lambda: queue.step_running, 15)
    pump(0.3)
    queue.stop()
    assert wait(lambda: not queue.active, 15)
    assert queue.items[0].status in ("skipped", "stopped") and queue.items[1].status == "stopped"


def test_a_failing_wait_fails_the_item(app):
    queue = app.services.queue
    queue.items.clear()
    queue.insert([queue_steps.new_step("wait_below", parameter="dummy_dmm_signal", value=-100.0, timeout=1.0)])
    queue.start()
    assert wait(lambda: not queue.active, 15)
    assert queue.items[0].status == "failed" and "not reached" in queue.items[0].message


def test_queue_files_script_and_crash_recovery(app, tmp_path):
    from mesoscopy.core.app_settings import AppSettings
    from mesoscopy.services import create_services

    queue, sweep, tab = app.services.queue, app.window.sweep_tab, app.window.queue_tab
    queue.items.clear()
    sweep.set_state(recipe("qf", [dimension(num=3)], advanced={"export": True, "save_plot": True}))
    sweep.add_to_queue()
    queue.insert([queue_steps.new_step("wait_stable", parameter="dummy_dac_Vtop", tol=0.01, dwell=1)])
    path, script = str(tmp_path / "q.json"), str(tmp_path / "q.py")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
    tab.save_queue()
    queue.items.clear()
    queue.changed.emit()
    tab.load_queue()
    assert len(queue.items) == 2 and queue_steps.is_step(queue.items[1].state)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (script, ""))
    tab.export_python()
    source = open(script).read()
    compile(source, script, "exec")
    assert "dond(" in source and "wait_stable" in source
    # as if the application died while the first item ran
    queue.items[0].status = "running"
    queue._set_state("running")
    queue._autosave()
    restarted = create_services(AppSettings(app.services.settings.file_name()))
    assert restarted.queue.interrupted_summary() is not None
    restarted.queue.restore_after_crash(True)
    assert restarted.queue.items[0].status == "waiting"
    queue.items[0].status = "waiting"
    queue._set_state("idle")
    queue._autosave()


# --------------------------------------------------------------------------------------------- the Data tab
def test_explorer_lists_runs_tags_and_notes(app):
    data = app.window.data_tab
    show(app, app.window.data_tab_widget)
    data.populate_database_files()
    data.refresh_experiments()
    pump(0.3)
    assert data.experiment_combo.count() >= 1
    data.experiment_combo.setCurrentIndex(0)
    data.on_experiment_changed()
    pump(0.4)
    assert data.runs_table.rowCount() >= 5
    from mesoscopy.core.run_tags import set_notes
    from mesoscopy.ui.tabs.run_table import ROLE_RUN

    data.runs_table.selectRow(0)
    data.on_run_selected()
    app.shown.menus.clear()
    data._show_run_menu(data.runs_table.visualRect(data.runs_table.model().index(0, 1)).center())
    assert hasattr(app.shown.menus[-1], "tag_picker")
    data.set_run_tag(0, "red")
    data._write_run_metadata(0, "notes", "explorer note", set_notes)
    run = data.runs_table.item(0, 1).data(ROLE_RUN)
    assert (run["tag"], run["notes"]) == ("red", "explorer note")
    data.delete_run_notes(0)
    assert data.runs_table.item(0, 1).data(ROLE_RUN)["notes"] == ""
    from mesoscopy.core.snapshot_diff import read_run_snapshot

    assert read_run_snapshot(data.current_db_path(), data.selected_run_id()).snapshot is not None
    data.compare_with_another_run()
    data.view_logs()
    assert data._log_viewer is not None


def test_a_change_from_the_live_plot_updates_the_explorer(app):
    from mesoscopy.ui.tabs.run_table import ROLE_RUN

    data, plot = app.window.data_tab, app.window.sweep_tab.plot_panel
    shown = data.current_db_path()
    plot._db_file, plot._run_id, plot._data = shown, 1, {"run_id": 1}
    plot._write_tag(1, "blue")
    row = next(r for r in range(data.runs_table.rowCount()) if data.runs_table.item(r, 1).data(ROLE_RUN)["run_id"] == 1)
    assert data.runs_table.item(row, 1).data(ROLE_RUN)["tag"] == "blue"


# -------------------------------------------------------------------------------------- settings, about, instruments
def test_settings_apply_and_about_opens(app):
    from mesoscopy.ui.settings_dialog import SettingsDialog

    settings = app.services.settings
    dialog = SettingsDialog(app.window, settings, app.window.save_session)
    dialog.retry_spin.setValue(4)
    dialog.past_cache_spin.setValue(300)
    dialog.alarm_percent_spin.setValue(80)
    assert dialog.apply()
    assert settings.retry_attempts == 4 and settings.past_cache_mb == 300 and settings.alarm_percent == 80
    assert app.window.sweep_tab.plot_panel._past_cache_limit == 300 * 2 ** 20
    app.window.save_session()
    assert settings.session()
    app.window.open_settings()
    app.window.open_about()


def test_reconnect_and_disconnect_instruments(app, parameters):
    instruments = app.window.instruments_tab
    manager = instruments.manager
    show(app, app.window.instruments_tab_widget)
    names = [instruments.connected_instr_list.item(i).text() for i in range(instruments.connected_instr_list.count())]
    row = names.index("dummy_dmm")
    instruments.connected_instr_list.setCurrentRow(row)
    instruments.connected_instr_list.item(row).setSelected(True)
    assert manager.reconnect_selected_instruments()
    pump(0.5)
    assert parameters()["dummy_dmm_signal"]() is not None  # the experiment parameter follows the new instrument
    assert manager.disconnect_instruments(["dummy_scope"])
    pump(0.4)
    assert "spectrum" not in parameters()


def test_closing_ramps_the_changed_parameters_and_leaves_no_queue_behind(app, parameters):
    vtop = parameters()["dummy_dac_Vtop"]
    gate = app.services.station.instruments()["dummy_dac"].ch1  # its cache is still readable once the instrument is closed
    vtop(0.4)
    app.services.restore.mark_touched(vtop)
    app.window.close()
    pump(0.3)
    assert abs(gate.cache.get(get_if_invalid=False)) < 1e-9  # ramped to 0 before the instruments were disconnected
    assert not app.services.settings.queue_autosave().get("active")
