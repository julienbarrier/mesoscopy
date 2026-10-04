"""Tests of the parts of the program that need neither a window nor an instrument."""
import os
import threading
import types
from datetime import datetime

import numpy as np
import pytest
from qcodes.parameters import DelegateParameter, Parameter
from qcodes.validators import Numbers

from mesoscopy.core import queue_steps, recipes
from mesoscopy.core.alarms import allowed_range, thresholds
from mesoscopy.core.db_manager import database_name, next_database, prefix_of, sample_prefix
from mesoscopy.core.dry_run import check_request, ramp_seconds
from mesoscopy.core.fault_guard import RetryGuard, is_communication_error, leaf_parameters
from mesoscopy.core.grid_data import GridAxis, compact_grid
from mesoscopy.core.monitor_log import MonitorLog
from mesoscopy.core.predefined_actions import PREDEFINED, build_action
from mesoscopy.core.restore_history import RestoreHistory
from mesoscopy.core.wait_tools import WaitInterrupted, WaitTimeout, WaitTools


# ----------------------------------------------------------------------------------------------------------- waiting
class Reading:
    """A parameter-like object that returns the given readings one after the other."""

    name = "T"

    def __init__(self, *values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


def test_wait_below_returns_when_reached():
    WaitTools(sleep=lambda s: None).wait_below(Reading(5.0, 4.9, 4.4), 4.5, timeout=30, poll=0.0)


def test_wait_stable_needs_the_dwell_time():
    tools = WaitTools()
    elapsed = tools.wait_stable(Reading(*[4.3] * 200), tol=0.05, dwell=0.05, timeout=10, poll=0.01)
    assert elapsed >= 0.05


def test_wait_stable_restarts_when_the_value_leaves_the_band():
    readings = [4.0, 4.5, 4.3, 4.31, 4.29] + [4.30] * 100
    assert WaitTools().wait_stable(Reading(*readings), target=4.3, tol=0.05, dwell=0.05, timeout=10, poll=0.01) > 0.05


def test_wait_ends_on_stop():
    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()
    with pytest.raises(WaitInterrupted):
        WaitTools(stopped=stop.is_set).wait(30)


def test_wait_times_out():
    with pytest.raises(WaitTimeout):
        WaitTools().wait_until(lambda: False, timeout=0.1, poll=0.02, message="nothing")


def test_clocks_are_paused_while_waiting():
    events = []
    WaitTools(pause=lambda: events.append("pause"), resume=lambda: events.append("resume")).wait(0.05)
    assert events == ["pause", "resume"]


# ------------------------------------------------------------------------------------------------ retrying instruments
def test_communication_errors_are_told_from_others():
    assert is_communication_error(TimeoutError("visa timeout"))
    assert is_communication_error(ConnectionResetError())
    assert not is_communication_error(ValueError("outside the limits"))


def test_a_failing_read_is_retried_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("visa timeout")
        return 7.0

    source = Parameter("p", get_cmd=flaky, set_cmd=None)
    delegate = DelegateParameter("d", source=source)
    messages = []
    guard = RetryGuard(3, 0.01, threading.Event(), announce=messages.append)
    assert leaf_parameters(delegate) == [source]
    with guard.guard([delegate]):
        assert delegate() == 7.0
    assert guard.retries == 2 and len(messages) == 2
    assert "get" in vars(source)  # the original is back


def test_retries_give_up_and_other_errors_are_not_retried():
    source = Parameter("q", get_cmd=lambda: (_ for _ in ()).throw(TimeoutError("x")), set_cmd=None)
    with RetryGuard(1, 0.01, threading.Event()).guard([source]):
        with pytest.raises(TimeoutError):
            source()
    calls = []
    other = Parameter("r", get_cmd=lambda: calls.append(1) or (_ for _ in ()).throw(ValueError("bad")), set_cmd=None)
    with RetryGuard(3, 0.01, threading.Event()).guard([other]):
        with pytest.raises(ValueError):
            other()
    assert len(calls) == 1


# ------------------------------------------------------------------------------------------------------- queue steps
def test_queue_step_text_and_validation():
    step = queue_steps.new_step("wait_stable", parameter="T", use_target=True, value=4.2)
    assert recipes.title(step) == "Wait until T is stable at 4.2"
    assert recipes.problems(step) == []
    assert recipes.problems(queue_steps.new_step("set")) == ["it names no parameter"]
    assert queue_steps.estimate(queue_steps.new_step("wait", seconds=30)) == 30.0
    assert recipes.problems(queue_steps.new_step("repeat_until", expression="T() >")) != []


def test_queue_step_execute():
    history = RestoreHistory()
    gate = Parameter("B", set_cmd=None, initial_value=1.0)
    tools = WaitTools()
    assert queue_steps.execute(queue_steps.new_step("set", parameter="B", value=0.0), {"B": gate}, tools, history) == "done"
    assert gate() == 0.0 and history.was_touched(gate)
    assert queue_steps.execute(queue_steps.new_step("wait", seconds=0.05), {}, tools, history) == "done"
    repeat = queue_steps.new_step("repeat_until", expression="B() > 5", max_repeats=2)
    assert queue_steps.execute(repeat, {"B": gate}, tools, history) == "repeat"
    repeat[queue_steps.STEP_KEY]["count"] = 2
    assert queue_steps.execute(repeat, {"B": gate}, tools, history) == "done"
    stop = threading.Event()
    stop.set()
    assert queue_steps.execute(queue_steps.new_step("wait", seconds=30), {}, WaitTools(stopped=stop.is_set), history) == "stopped"


def test_a_missing_parameter_is_an_error():
    with pytest.raises(ValueError):
        queue_steps.execute(queue_steps.new_step("set", parameter="nope", value=1), {}, WaitTools(), RestoreHistory())


# ------------------------------------------------------------------------------------------------------ monitor log
def test_monitor_log_files(tmp_path):
    folder, when = str(tmp_path), datetime(2026, 10, 3, 14, 25, 30)
    log = MonitorLog()
    assert log.configure(folder, "DB012_00", ["T", "B"], when)
    assert os.path.basename(log.path) == "monitor_DB012_00_20261003.log"
    assert not log.configure(folder, "DB012_00", ["T", "B"], when)  # nothing changed: no new file
    log.write({"T": 4.2, "B": None}, when)
    lines = open(log.path).read().splitlines()
    assert lines == ["timestamp\tT\tB", "2026-10-03 14:25:30\t4.2\t"]
    log.configure(folder, "DB012_00", ["T", "B", "V"], when)  # other columns: a file of its own
    assert os.path.basename(log.path) == "monitor_DB012_00_20261003_142530.log"
    restarted = MonitorLog()
    restarted.configure(folder, "DB012_00", ["T", "B"], when)  # same columns: the rows are added
    assert os.path.basename(restarted.path) == "monitor_DB012_00_20261003.log"
    assert log.configure(folder, "DB013_00", ["T", "B", "V"], when) and "DB013_00" in log.path
    assert log.configure("", "x", ["T"]) and log.path is None


# ------------------------------------------------------------------------------------------------------- grid data
def test_compact_grid_keeps_the_values_and_saves_memory():
    outer, inner = np.meshgrid(np.linspace(0, 1, 400), np.linspace(-1, 1, 300), indexing="ij")
    values = np.sin(5 * outer) * np.cos(3 * inner)
    columns = {"a": outer, "b": inner, "v": values}
    compact = compact_grid(columns, {"v"})
    assert isinstance(compact["a"], GridAxis) and isinstance(compact["b"], GridAxis)
    assert sum(c.nbytes for c in compact.values()) < 0.25 * sum(c.nbytes for c in columns.values())
    assert np.array_equal(compact["a"][:], outer.ravel()) and np.array_equal(compact["b"][5000:5100], inner.ravel()[5000:5100])
    assert np.abs(compact["v"] - values.ravel()).max() < 1e-6


def test_compact_grid_leaves_snakes_and_small_grids_alone():
    outer, inner = np.meshgrid(np.linspace(0, 1, 400), np.linspace(-1, 1, 300), indexing="ij")
    snake = inner.copy()
    snake[1::2] = snake[1::2][:, ::-1]
    assert not isinstance(compact_grid({"a": outer, "s": snake, "v": outer}, {"v"})["s"], GridAxis)
    small = compact_grid({"a": outer[:10, :10], "v": inner[:10, :10]}, {"v"})
    assert not isinstance(small["a"], GridAxis) and small["v"].dtype == np.float64


# ------------------------------------------------------------------------------------------------------ databases
def test_database_naming(tmp_path):
    assert sample_prefix("Hall bar #2") == "Hall_bar_2"
    assert database_name("Hall_bar", 3) == "Hall_bar_03.db" and prefix_of("Hall_bar_03.db") == "Hall_bar"
    assert os.path.basename(next_database(str(tmp_path), "S")) == "S_00.db"
    (tmp_path / "S_00.db").write_text("")
    (tmp_path / "S_04.db").write_text("")
    assert os.path.basename(next_database(str(tmp_path), "S")) == "S_05.db"


# ---------------------------------------------------------------------------------------------------------- alarms
def test_alarm_thresholds_follow_the_validator():
    gate = Parameter("g", set_cmd=None, vals=Numbers(-2, 2))
    assert allowed_range(gate) == (-2.0, 2.0)
    assert thresholds(gate, 90) == (pytest.approx(-1.8), pytest.approx(1.8))
    assert thresholds(Parameter("free", set_cmd=None), 90) == (None, None)


# ------------------------------------------------------------------------------------------------------------ dry run
def make_services(alarm_on=None):
    alarms = types.SimpleNamespace(has=lambda p: p is alarm_on, thresholds=lambda p: (-1.8, 1.8), describe=lambda p: "90 %")
    return types.SimpleNamespace(
        data=types.SimpleNamespace(folder=os.getcwd()), alarms=alarms,
        registry=types.SimpleNamespace(breakout_items=lambda: [], definitions={}))


def make_request(sweeps, measured, **extra):
    return types.SimpleNamespace(
        sweeps=sweeps, measured=measured, repeat=1, breakout=extra.get("breakout", False),
        state={"dimensions": [{"class": "LinSweep", "component": ["g"], "start": 0, "stop": 1, "num": 11, "delay": 0.01}]})


def test_dry_run_reports_limits_alarms_and_time():
    from qcodes.dataset import LinSweep, TogetherSweep

    gate = Parameter("gate", set_cmd=None, get_cmd=None, initial_value=0.0, vals=Numbers(-2, 2), unit="V", step=0.1, inter_delay=0.05)
    meter = Parameter("meter", get_cmd=lambda: 1.0)
    services = make_services(alarm_on=gate)
    report = check_request(make_request([LinSweep(gate, -3, 3, 61, 0.01)], [("m", meter)]), services)
    assert not report.ok and any("not allowed" in e for e in report.errors)
    assert any("alarm" in w for w in report.warnings)
    fine = check_request(make_request([LinSweep(gate, -1, 1, 21, 0.01)], [("m", meter)]), services)
    assert fine.ok and fine.seconds is not None
    assert ramp_seconds(1.0, gate) == pytest.approx(0.5)  # ten steps of 0.1 V, one every 0.05 s
    other = Parameter("other", set_cmd=None, get_cmd=None, initial_value=0.0)
    together = TogetherSweep(LinSweep(gate, 0, 1, 5, 0.0), LinSweep(other, 0, 1, 5, 0.0))
    assert check_request(make_request([together], [("m", meter)]), services).ok  # a TogetherSweep has no delay of its own


def test_dry_run_refuses_what_cannot_be_read():
    from qcodes.dataset import LinSweep

    gate = Parameter("gate2", set_cmd=None, get_cmd=None, initial_value=0.0)
    request = make_request([LinSweep(gate, 0, 1, 3, 0.0)], [("x", types.SimpleNamespace(full_name="x", gettable=False, root_instrument=None))])
    assert any("cannot be read" in e for e in check_request(request, make_services()).errors)


# -------------------------------------------------------------------------------------- what is ramped at the end
def test_only_changed_nonzero_parameters_are_ramped():
    from mesoscopy.services.ramp import RampService

    changed, never, zero = (Parameter(n, set_cmd=None, initial_value=v) for n, v in (("a", 1.0), ("b", 2.0), ("c", 0.0)))
    definitions = {n: types.SimpleNamespace(kind="instrument", max_ramp_rate=None) for n in "abc"}
    registry = types.SimpleNamespace(parameters=lambda: {"a": changed, "b": never, "c": zero}, definitions=definitions)
    history = RestoreHistory()
    ramp = RampService(types.SimpleNamespace(registry=registry, restore=history, gateway=None))
    assert ramp.settable_parameters(changed_only=True) == []
    history.mark_touched(changed)
    history.mark_touched(zero)
    assert [p.name for p in ramp.settable_parameters(changed_only=True)] == ["a"]
    assert len(ramp.settable_parameters()) == 3


# ------------------------------------------------------------------------------------------- actions and scripts
def test_predefined_actions_are_one_line_and_compile():
    for entry in PREDEFINED:
        action = build_action(entry, "Vtop" if entry.needs else "")
        assert "\n" not in action["code"]
        compile(action["code"], "<action>", "exec")


def test_exported_script_compiles():
    from mesoscopy.core.export_python import generate_script

    state = {"experiment_name": "e", "measurement_name": "m", "measured": [{"path": ["T"]}],
             "dimensions": [{"class": "LinSweep", "component": ["T"], "start": "0", "stop": "1", "num": 3, "delay": "0"}],
             "advanced": {"enter": [{"name": "w", "code": "wait_stable(T, tol=0.02, dwell=60)", "enabled": True}],
                          "export": True, "export_type": "csv", "save_plot": True, "plot_format": "png"}}
    definitions = [{"name": "T", "kind": "instrument", "source": ["g", "T"], "unit": "K", "gain": 1, "min_value": None,
                    "max_value": None, "max_ramp_rate": None, "origin": "user", "expression": "", "breakout": {}}]
    steps = [queue_steps.new_step("wait_stable", parameter="T", use_target=True, value=4.2), state,
             queue_steps.new_step("set", parameter="T", value=1.0)]
    context = {"station_file": "s.yaml", "components": ["g"], "database": "d.db", "sample_name": "s",
               "stop_on_failure": True, "breakout_mode": "any", "use_threads": False}
    script = generate_script(steps, context, definitions)
    compile(script, "script.py", "exec")
    assert "WAIT_FUNCTIONS" in script and "export_settings" in script and "save_dataset_plots" in script


def test_recipe_estimate_counts_delays_and_ramps():
    state = {"dimensions": [{"class": "LinSweep", "component": ["g"], "start": "0", "stop": "1", "num": 11, "delay": "0.5"}]}
    assert recipes.estimate(state) == pytest.approx(5.5)
    assert recipes.estimate(state, lambda path: 0.5) == pytest.approx(5.5 + 2.0)  # 1 V at 0.5 V/s
