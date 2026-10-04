"""The live feed of a run (``core/live_feed``), checked against what the database holds (``core/live_data``)."""
import numpy as np
import pytest
from qcodes.dataset import LinSweep, dond, initialise_or_create_database_at, load_or_create_experiment
from qcodes.instrument import Instrument
from qcodes.parameters import Parameter, ParameterWithSetpoints
from qcodes.validators import Arrays, ComplexNumbers

from mesoscopy.core.live_data import fetch_run_data
from mesoscopy.core.live_feed import capture_live_runs
from mesoscopy.core.run_tags import get_run_tags, set_notes, set_tag


class Bench(Instrument):
    """Two gates and a trace that follows the first one."""

    def __init__(self, name):
        super().__init__(name)
        self.add_parameter("a", set_cmd=None, initial_value=0.0)
        self.add_parameter("b", set_cmd=None, initial_value=0.0)
        self.add_parameter("n", set_cmd=None, initial_value=8)
        self.add_parameter("axis", get_cmd=lambda: np.linspace(0, 1, 8), vals=Arrays(shape=(8,)))
        self.add_parameter("trace", parameter_class=ParameterWithSetpoints, setpoints=(self.axis,), get_cmd=self._trace,
                           vals=Arrays(shape=(8,)))

    def _trace(self):
        return np.linspace(0, 1, 8) * (1 + self.a())


@pytest.fixture(scope="module")
def bench():
    instrument = Bench("live_bench")
    yield instrument
    instrument.close()


@pytest.fixture()
def experiment(tmp_path):
    db = str(tmp_path / "live.db")
    initialise_or_create_database_at(db)
    return db, load_or_create_experiment("e", "s")


def measure(experiment, *args, **kwargs):
    db, exp = experiment
    lives = []
    with capture_live_runs(lives.append):
        dond(*args, exp=exp, show_progress=False, do_plot=False, write_period=0.05, **kwargs)
    return db, lives


def same_data(live, db):
    snapshot, reference = live.snapshot(), fetch_run_data(db, live.run_id)
    assert snapshot["completed"] and reference["completed"]
    assert snapshot["setpoints"] == reference["setpoints"] and snapshot["dependents"] == reference["dependents"]
    assert snapshot["single_curve"] == reference["single_curve"]
    assert snapshot["trace_length"] == reference["trace_length"]
    for name, values in reference["arrays"].items():
        assert np.allclose(np.asarray(snapshot["arrays"][name]), np.asarray(values), atol=1e-6, equal_nan=True), name
    return snapshot


def test_a_1d_sweep_is_followed_from_its_rows(experiment, bench):
    meter = Parameter("m", get_cmd=lambda: bench.a() * 2)
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 11, 0), meter)
    assert not lives[0].uses_cache
    assert same_data(lives[0], db)["n_points"] == 11


def test_a_map_is_read_from_the_cache(experiment, bench):
    meter = Parameter("m2", get_cmd=lambda: bench.a() + bench.b())
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 6, 0), LinSweep(bench.b, 0, 1, 5, 0), meter)
    assert lives[0].uses_cache
    assert same_data(lives[0], db)["n_points"] == 30


def test_the_cache_can_be_switched_off(experiment, bench):
    meter = Parameter("m3", get_cmd=lambda: 1.0)
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 4, 0), LinSweep(bench.b, 0, 1, 3, 0), meter, in_memory_cache=False)
    assert not lives[0].uses_cache
    assert same_data(lives[0], db)["n_points"] == 12


def test_complex_values_stay_complex(experiment, bench):
    z = Parameter("z", get_cmd=lambda: complex(bench.a(), -bench.a()), vals=ComplexNumbers())
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 5, 0), z)
    snapshot = same_data(lives[0], db)
    assert np.iscomplexobj(snapshot["arrays"]["z"])


def test_traces_get_one_row_per_acquisition(experiment, bench):
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 4, 0), bench.trace)
    snapshot = same_data(lives[0], db)
    assert snapshot["trace_length"] == 8 and snapshot["n_points"] == 32


def test_scalars_and_a_trace_in_one_run_are_not_mixed(experiment, bench):
    """QCoDeS writes a row for the scalars and another for the trace: they must keep their own columns."""
    meter = Parameter("m4", get_cmd=lambda: bench.a() * 3)
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 6, 0), meter, bench.trace)
    snapshot = same_data(lives[0], db)
    assert snapshot["trace_length"] == 8
    lengths = {name: len(values) for name, values in snapshot["arrays"].items()}
    assert lengths["m4"] == 6 and lengths[bench.trace.register_name] == 48


def test_a_finished_map_is_kept_compact(experiment, bench):
    meter = Parameter("m5", get_cmd=lambda: 1.0)
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 250, 0), LinSweep(bench.b, 0, 1, 250, 0), meter)
    arrays = lives[0].snapshot()["arrays"]
    assert arrays[bench.a.register_name].nbytes < 10_000  # the unique values of the axis, not 62 500 points
    assert arrays["m5"].dtype == np.float32


def test_tags_and_notes_are_written_to_the_run(experiment, bench):
    meter = Parameter("m6", get_cmd=lambda: 1.0)
    db, lives = measure(experiment, LinSweep(bench.a, 0, 1, 3, 0), meter)
    run = lives[0].run_id
    assert get_run_tags(db, run) == ("", "")
    set_tag(db, run, "green")
    set_notes(db, run, "leaky above 1 V")
    assert get_run_tags(db, run) == ("green", "leaky above 1 V")
    with pytest.raises(ValueError):
        set_tag(db, run, "pink")
