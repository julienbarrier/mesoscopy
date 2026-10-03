"""Check a measurement before it starts (no Qt): limits, ramp rates, time and size.

``check_request`` looks at a ``RunRequest`` without touching an instrument (it reads the last known values only) and
returns a ``Report``: errors (the run cannot work, so it is not started), warnings (it will probably do something
unwanted) and information (what it will take). The Run button of the Measurement tab and the queue run it before a
measurement starts; the "Check setup" button shows the whole report.
"""
import math
import os
import shutil
from dataclasses import dataclass, field

import numpy as np
from qcodes.instrument import Instrument

from mesoscopy.core import recipes
from mesoscopy.core.parameter_io import cached_value
from mesoscopy.core.run_progress import format_estimate
from mesoscopy.experiment.snake import real_parameter

ERROR, WARNING, INFO = "error", "warning", "info"
SAMPLES = 20                 # setpoints (besides the extremes) tried against a parameter's validator
BYTES_PER_VALUE = 24         # a stored value, with the database overhead (rough)
LARGE_GRID_POINTS = 5_000_000


@dataclass
class Report:
    findings: list = field(default_factory=list)   # [(level, text)]
    seconds: float = None                          # estimated duration, None when it cannot be told

    def add(self, level, text):
        self.findings.append((level, text))

    def of(self, level):
        return [text for lev, text in self.findings if lev == level]

    @property
    def errors(self):
        return self.of(ERROR)

    @property
    def warnings(self):
        return self.of(WARNING)

    @property
    def ok(self):
        return not self.errors

    def text(self):
        """The report as lines, errors first."""
        marks = {ERROR: "ERROR", WARNING: "Warning", INFO: "Info"}
        order = {ERROR: 0, WARNING: 1, INFO: 2}
        return "\n".join(f"{marks[level]}: {text}" for level, text in sorted(self.findings, key=lambda f: order[f[0]]))


def ramp_seconds(distance, parameter):
    """Seconds QCoDeS needs to move ``parameter`` by ``distance``: the steps of its ramp, one inter-delay each. 0 when it
    has no maximum ramp rate (it is set in one go)."""
    step, delay = getattr(parameter, "step", None), getattr(parameter, "inter_delay", None)
    if not step or not delay or distance <= 0:
        return 0.0
    return math.ceil(distance / step - 1e-9) * float(delay)


def _axis_setpoints(sweep):
    """[(real parameter, setpoint values)] of an axis: one parameter, or the several of a TogetherSweep."""
    found = []
    for sub in getattr(sweep, "sweeps", [sweep]):
        values = getattr(sub.param, "values", None)  # a snake axis sweeps an index: the real values are kept in it
        found.append((real_parameter(sub.param), np.asarray(sub.get_setpoints() if values is None else values, float)))
    return found


def _sample(values):
    """The extremes, the ends and some points in between, without repeats."""
    if len(values) <= SAMPLES + 4:
        return list(values)
    picks = {values.argmin(), values.argmax(), 0, len(values) - 1, *np.linspace(0, len(values) - 1, SAMPLES).astype(int)}
    return [values[i] for i in sorted(picks)]


def _unit(parameter):
    unit = getattr(parameter, "unit", "")
    return f" {unit}" if unit else ""


def _check_limits(report, parameter, values):
    for value in _sample(values):
        try:
            parameter.validate(float(value))
        except Exception as e:
            report.add(ERROR, f"{parameter.full_name}: {value:g}{_unit(parameter)} is not allowed ({e}).")
            return


def _check_alarms(report, services, parameter, values):
    alarms = services.alarms
    if not alarms.has(parameter):
        return
    low, high = alarms.thresholds(parameter)
    hit = [v for v in (values.min(), values.max()) if (high is not None and v >= high) or (low is not None and v <= low)]
    if hit:
        report.add(WARNING, f"{parameter.full_name}: the sweep reaches {hit[0]:g}{_unit(parameter)}, where its alarm goes off "
                            f"({alarms.describe(parameter)}).")


def check_request(request, services, check_database=True):
    """The report on a measurement about to start. ``check_database=False`` leaves the database folder out (the
    run controller looks at it itself)."""
    report = Report()
    sweeps, measured = request.sweeps, request.measured

    if check_database and not services.data.folder:
        report.add(ERROR, "No database folder is selected (Data tab).")
    if not measured:
        report.add(ERROR, "Nothing is measured.")
    for alias, parameter in measured:
        root = getattr(parameter, "root_instrument", None)
        if root is not None and not Instrument.is_valid(root):
            report.add(ERROR, f"{parameter.full_name}: its instrument is closed. Load it again.")
        elif not parameter.gettable:
            report.add(ERROR, f"{parameter.full_name} cannot be read.")
    if request.breakout and not services.registry.breakout_items():
        report.add(WARNING, "'Stop on breakout conditions' is ticked but no experiment parameter has a breakout condition.")

    # the sweeps: limits, alarms, ramp rates and the first move
    move_seconds, counts = [], []
    for number, sweep in enumerate(sweeps, start=1):
        axis = _axis_setpoints(sweep)
        counts.append(sweep.num_points)
        if sweep.num_points < 1 or any(len(v) < 1 for _, v in axis):
            report.add(ERROR, f"Axis {number} has no points.")
            continue
        if len({len(v) for _, v in axis}) > 1:
            report.add(ERROR, f"Axis {number}: the parameters swept together have different numbers of points.")
        for parameter, values in axis:
            if not parameter.settable:
                report.add(ERROR, f"{parameter.full_name} cannot be set.")
                continue
            _check_limits(report, parameter, values)
            _check_alarms(report, services, parameter, values)
            current = cached_value(parameter)
            try:
                first_move = abs(float(values[0]) - float(current))
            except (TypeError, ValueError):
                first_move = None
            has_rate = bool(getattr(parameter, "step", None) and getattr(parameter, "inter_delay", None))
            if first_move:
                move_seconds.append(ramp_seconds(first_move, parameter))
                if not has_rate and first_move > 1e-12 * max(abs(float(values[0])), 1.0):
                    report.add(WARNING, f"{parameter.full_name} has no maximum ramp rate (Parameter explorer): the first "
                                        f"move, from {float(current):g} to {float(values[0]):g}{_unit(parameter)}, is made in one go.")
            if len(values) > 1:
                point_move = ramp_seconds(float(np.max(np.abs(np.diff(values)))), parameter)
                if point_move > max(sweep.delay, 0.0) + 1e-9:
                    report.add(INFO, f"{parameter.full_name}: each point takes at least {point_move:g} s to reach (limited by "
                                     f"the ramp rate), more than the delay of {sweep.delay:g} s.")

    points = math.prod(counts) if counts else 1
    columns = len(measured) + len(sweeps)
    if points >= LARGE_GRID_POINTS:
        report.add(WARNING, f"{points:,} points: dond keeps the whole grid in memory (about "
                            f"{points * columns * 8 / 2**20:,.0f} MB).")
    size = points * columns * BYTES_PER_VALUE * max(request.repeat, 1)
    folder = services.data.folder
    if check_database and folder and os.path.isdir(folder):
        free = shutil.disk_usage(folder).free
        if free < max(3 * size, 500 * 2**20):
            report.add(WARNING, f"Only {free / 2**30:.1f} GB are free where the database is; this measurement writes about "
                                f"{size / 2**20:,.0f} MB.")

    # the time: the delays and ramps of the recipe, plus the first move (the slowest of the parameters, which ramp together)
    seconds = recipes.estimate(request.state, recipes.rate_lookup(services.registry))
    if seconds is not None:
        report.seconds = seconds + (max(move_seconds) if move_seconds else 0.0)
        report.add(INFO, f"{points:,} points" + (f" x {request.repeat} repetitions" if request.repeat > 1 else "")
                   + f", at least {format_estimate(report.seconds)}: delays and ramps"
                   + (f", with {format_estimate(max(move_seconds))} to reach the start values" if move_seconds and max(move_seconds) else "")
                   + "; the time the instruments take to measure is not included.")
    return report
