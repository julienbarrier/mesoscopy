"""Recipes: Measurement tab setups kept in a queue (no widgets).

A recipe is the plain data of ``SweepTab.get_state()``. This module describes one in words (the lines of the queue
list and of its detail pane), estimates its duration, and reads and writes queue files.
"""
import json

import numpy as np

from mesoscopy.core.dond_options import describe_changes, normalise_advanced
from mesoscopy.core.array_expression import evaluate_array_expression
from mesoscopy.core import queue_steps
from mesoscopy.core.run_progress import format_estimate

QUEUE_FILE_VERSION = 1


def _label(path):
    """Name of the experiment parameter a component path starts with."""
    return path[0] if path else "?"


def axis_label(dimension):
    """One axis in words: 'Vtop 0 > 1 (101 pts)'."""
    kind = dimension.get("class", "")
    points = axis_points(dimension)
    count = f" ({points} pts)" if points is not None else ""
    if kind == "TogetherSweep":
        names = " + ".join(_label(path) for path in dimension.get("together") or [])
        return f"{names or '?'} together{count}"
    name = _label(dimension.get("component") or [])
    if kind == "ArraySweep":
        return f"{name} array{count}"
    return f"{name} {dimension.get('start', '?')} > {dimension.get('stop', '?')}{count}"


def axis_points(dimension):
    """Number of points of an axis, None if its fields are incomplete."""
    try:
        if dimension.get("class") == "ArraySweep":
            return len(evaluate_array_expression(dimension.get("array", "")))
        return int(dimension.get("num"))
    except (ValueError, TypeError):
        return None


def repetitions(state):
    repeat = state.get("repeat") or {}
    return int(repeat.get("times", 1)) if repeat.get("enabled") else 1


def back_and_forth(state):
    """Every other repetition sweeps backwards: one axis, repeated, and the option ticked."""
    return len(state.get("dimensions") or []) == 1 and repetitions(state) > 1 and bool(state.get("back_and_forth"))


def rate_lookup(registry):
    """``rate_of(path)``: the maximum ramp rate (unit per second) of the experiment parameter a component path starts
    with, None when it has none (or is unknown)."""
    def rate_of(path):
        definition = registry.definitions.get(path[0]) if path else None
        return definition.max_ramp_rate if definition is not None else None
    return rate_of


def _components(dimension):
    """[(path, setpoints)] of the parameters an axis sets: one, or the two of a TogetherSweep. Raises ValueError when
    the fields are incomplete."""
    kind = dimension.get("class")
    if kind == "ArraySweep":
        return [(dimension.get("component") or [], np.asarray(evaluate_array_expression(dimension.get("array", "")), float))]
    num = int(dimension.get("num"))
    if kind == "TogetherSweep":
        return [(path or [], np.linspace(float(start), float(stop), num)) for path, start, stop in zip(
            dimension.get("together") or [], dimension.get("together_starts") or [], dimension.get("together_stops") or [])]
    start, stop = float(dimension.get("start")), float(dimension.get("stop"))
    values = np.geomspace(start, stop, num) if kind == "LogSweep" else np.linspace(start, stop, num)
    return [(dimension.get("component") or [], values)]


def axis_timing(dimension, rate_of=None):
    """(points, delay, ramp seconds along the axis, seconds to go back from its end to its start) of an axis, or None
    when its fields are incomplete. The ramp time of a move is its length over the maximum ramp rate of the
    parameter (the slowest of them for a TogetherSweep); a parameter without a rate is set at once."""
    try:
        delay = float(dimension.get("delay", 0))
        components = _components(dimension)
    except (ValueError, TypeError):
        return None
    points = len(components[0][1]) if components else 0
    steps, back = np.zeros(max(points - 1, 0)), 0.0
    for path, values in components:
        rate = rate_of(path) if rate_of else None
        if rate and points > 1:
            steps = np.maximum(steps, np.abs(np.diff(values)) / rate)
            back = max(back, abs(values[-1] - values[0]) / rate)
    return points, max(delay, 0.0), float(steps.sum()), back


def estimate(state, rate_of=None):
    """Estimated duration in seconds (None when the fields are incomplete): the delay at every point, and, with
    ``rate_of``, the time to ramp the swept parameters from point to point, to bring an inner axis back to its start
    on every step of the axis outside it, and to go back to the start between repetitions. The first move to the
    start values, and the time the instruments take to measure, are not known and not included."""
    if queue_steps.is_step(state):
        return queue_steps.estimate(state)
    timings = []
    for dimension in state.get("dimensions") or []:
        timing = axis_timing(dimension, rate_of)
        if timing is None:
            return None
        timings.append(timing)
    snake = len(timings) == 2 and bool(state.get("snake"))
    inner, inner_back = 0.0, 0.0  # one pass of the axis inside, and its way back
    for index in range(len(timings) - 1, -1, -1):
        points, delay, ramp, back = timings[index]
        inner = points * (delay + inner) + ramp + (points - 1) * inner_back
        inner_back = 0.0 if snake and index == len(timings) - 1 else back
    times = repetitions(state)
    returns = 0.0 if back_and_forth(state) else sum(t[3] for t in timings)  # going back and forth needs no return
    return inner * times + (times - 1) * returns


def title(state):
    """Name of the recipe in the list: its measurement name (a step: what it does)."""
    if queue_steps.is_step(state):
        return queue_steps.title(state)
    return (state.get("measurement_name") or "").strip() or "(unnamed)"


def advanced_items(state):
    """What the advanced settings (dond options) change in a recipe, as short phrases."""
    axes = [(bool(d.get("get_after_set")), d.get("actions") or []) for d in state.get("dimensions") or []]
    return describe_changes(normalise_advanced(state.get("advanced")), axes)


def summary(state, rate_of=None):
    """The second line of the list: the axes, repetitions and measured parameters in a few words."""
    if queue_steps.is_step(state):
        return queue_steps.summary(state)
    dimensions = state.get("dimensions") or []
    parts = [" x ".join(axis_label(d) for d in dimensions) if dimensions else "single acquisition"]
    if len(dimensions) == 2 and state.get("snake"):
        parts.append("snake")
    if repetitions(state) > 1:
        parts.append(f"repeat x{repetitions(state)}" + (" back and forth" if back_and_forth(state) else ""))
    seconds = estimate(state, rate_of)
    if seconds:
        parts.append(format_estimate(seconds))
    return " | ".join(parts)


def description(state, rate_of=None):
    """The detail pane: the recipe as lines of text."""
    if queue_steps.is_step(state):
        return queue_steps.description(state)
    lines = [f"Experiment: {state.get('experiment_name') or '(none)'}",
             f"Measurement: {title(state)}"]
    dimensions = state.get("dimensions") or []
    if not dimensions:
        lines.append("No sweep axis: a single acquisition")
    for index, dimension in enumerate(dimensions, start=1):
        delay = dimension.get("delay")
        lines.append(f"Axis {index}: {axis_label(dimension)}" + (f", delay {delay} s" if delay not in (None, "") else ""))
    measured = [entry.get("alias") or _label(entry.get("path") or []) for entry in state.get("measured") or []]
    lines.append("Measured: " + (", ".join(measured) if measured else "(nothing)"))
    options = [("Snake sweep", state.get("snake") and len(dimensions) == 2),
               (f"Repeat x{repetitions(state)}", repetitions(state) > 1),
               ("Sweep back and forth", back_and_forth(state)),
               ("Stop on breakout conditions", state.get("breakout")),
               ("Ramp to 0 when finished", state.get("ramp_to_zero"))]
    lines += [name for name, on in options if on]
    lines += [f"Advanced: {item}" for item in advanced_items(state)]
    seconds = estimate(state, rate_of)
    if seconds:
        lines.append(f"Estimated time: {format_estimate(seconds)} (sweep delays and ramps of parameters that have a maximum ramp rate)")
    return "\n".join(lines)


def problems(state):
    """What makes a recipe impossible to run, whatever the instruments: [] when it can be tried."""
    if queue_steps.is_step(state):
        return queue_steps.problems(state)
    found = []
    if not (state.get("measurement_name") or "").strip():
        found.append("it has no measurement name")
    if not state.get("measured"):
        found.append("it measures nothing")
    return found


# ----- queue files -----
def dump_queue(items, stop_on_failure):
    """Text of a queue file for ``items`` (a list of recipe states)."""
    return json.dumps({"version": QUEUE_FILE_VERSION, "stop_on_failure": bool(stop_on_failure),
                       "items": [{"state": state} for state in items]}, indent=2)


def load_queue(text):
    """(recipe states, stop_on_failure) from the text of a queue file. Raises ValueError if it is not one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not a queue file ({e})") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("not a queue file")
    states = []
    for entry in data["items"]:
        state = entry.get("state") if isinstance(entry, dict) else None
        if not isinstance(state, dict):
            raise ValueError("a queue entry has no recipe")
        states.append(state)
    return states, bool(data.get("stop_on_failure", True))
