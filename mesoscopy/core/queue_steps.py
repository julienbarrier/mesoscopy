"""Steps of the queue besides measurements: waiting for a condition, setting a parameter, repeating until a condition
holds (no Qt).

A queue item is normally a recipe (the Measurement tab). A step is an item whose state is ``{"step": {...}}``:

* ``wait``          a fixed time;
* ``wait_below`` / ``wait_above``   until a parameter reads below / above a value;
* ``wait_stable``   until a parameter stays within a tolerance for a dwell time (around a target, if one is given);
* ``set``           bring a parameter to a value (at its maximum ramp rate);
* ``repeat_until``  after a measurement: if the condition (a Python expression of the experiment parameters, e.g.
                    ``T() > 10``) does not hold yet, the measurement before it and this step are queued again, at most
                    ``max_repeats`` times.

Steps run in the instrument gateway like any user action, and end at once when the queue is stopped or skipped.
"""
import numpy as np

from mesoscopy.core.wait_tools import WaitInterrupted

STEP_KEY = "step"
KINDS = {
    "wait": "Wait a fixed time",
    "wait_below": "Wait until a parameter is below",
    "wait_above": "Wait until a parameter is above",
    "wait_stable": "Wait until a parameter is stable",
    "set": "Set a parameter",
    "repeat_until": "Repeat the measurement above until",
}
DEFAULTS = {
    "wait": {"seconds": 60.0},
    "wait_below": {"parameter": "", "value": 4.5, "timeout": 3600.0},
    "wait_above": {"parameter": "", "value": 0.0, "timeout": 3600.0},
    "wait_stable": {"parameter": "", "use_target": False, "value": 0.0, "tol": 0.02, "dwell": 60.0, "timeout": 3600.0},
    "set": {"parameter": "", "value": 0.0},
    "repeat_until": {"expression": "", "max_repeats": 10, "count": 0},
}
NEEDS_PARAMETER = ("wait_below", "wait_above", "wait_stable", "set")


def new_step(kind, **fields):
    """The state of a queue item that is a step of ``kind`` (the defaults, then ``fields``)."""
    return {STEP_KEY: {"kind": kind, **DEFAULTS[kind], **fields}}


def is_step(state):
    return isinstance(state, dict) and isinstance(state.get(STEP_KEY), dict) and state[STEP_KEY].get("kind") in KINDS


def _g(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def title(state):
    s = state[STEP_KEY]
    kind, p = s["kind"], s.get("parameter") or "?"
    return {
        "wait": f"Wait {_g(s.get('seconds', 0))} s",
        "wait_below": f"Wait until {p} < {_g(s.get('value', 0))}",
        "wait_above": f"Wait until {p} > {_g(s.get('value', 0))}",
        "wait_stable": f"Wait until {p} is stable" + (f" at {_g(s.get('value', 0))}" if s.get("use_target") else ""),
        "set": f"Set {p} = {_g(s.get('value', 0))}",
        "repeat_until": f"Repeat until {s.get('expression') or '?'}",
    }[kind]


def summary(state):
    s = state[STEP_KEY]
    kind = s["kind"]
    if kind in ("wait_below", "wait_above"):
        return f"step | timeout {_g(s.get('timeout'))} s" if s.get("timeout") else "step | no timeout"
    if kind == "wait_stable":
        return f"step | within +-{_g(s.get('tol'))} for {_g(s.get('dwell'))} s" + (
            f" | timeout {_g(s['timeout'])} s" if s.get("timeout") else "")
    if kind == "repeat_until":
        return f"step | at most {int(s.get('max_repeats', 0))} repeats, done {int(s.get('count', 0))}"
    return "step"


def description(state):
    s = state[STEP_KEY]
    lines = [f"Step: {KINDS[s['kind']]}", title(state)]
    for key, label in (("timeout", "Timeout (s)"), ("tol", "Tolerance"), ("dwell", "Dwell (s)"), ("max_repeats", "At most repeats")):
        if s.get(key) not in (None, ""):
            lines.append(f"{label}: {_g(s[key])}")
    if s["kind"] == "repeat_until":
        lines.append("Queues the measurement before it again while the expression is false.")
    return "\n".join(lines)


def estimate(state):
    """Seconds, when the step has a known duration (a fixed wait), else None."""
    s = state[STEP_KEY]
    return float(s.get("seconds", 0)) if s["kind"] == "wait" else None


def problems(state):
    """What makes a step impossible to run: []  when it can be tried."""
    s = state[STEP_KEY]
    found = []
    if s["kind"] in NEEDS_PARAMETER and not s.get("parameter"):
        found.append("it names no parameter")
    if s["kind"] == "repeat_until":
        try:
            compile(s.get("expression") or "", "<condition>", "eval")
        except SyntaxError as e:
            found.append(f"the condition is not valid Python ({e.msg})")
        if not (s.get("expression") or "").strip():
            found.append("it has no condition")
    if s["kind"] == "wait" and not float(s.get("seconds", 0)) >= 0:
        found.append("the time is negative")
    return found


def parameter_names(state):
    s = state.get(STEP_KEY) or {}
    return [s["parameter"]] if s.get("parameter") else []


def execute(state, parameters, tools, history):
    """Run a step (in a gateway thread). ``parameters``: {name: experiment parameter}; ``tools``: a ``WaitTools``;
    ``history``: the RestoreHistory (a set goes through it, so that the parameter counts as changed).
    Returns "done", "stopped", or, for ``repeat_until``, "repeat" (the condition does not hold yet) / "done"."""
    s = state[STEP_KEY]
    kind = s["kind"]
    try:
        parameter = None
        if kind in NEEDS_PARAMETER:
            parameter = parameters.get(s["parameter"])
            if parameter is None:
                raise ValueError(f"the parameter '{s['parameter']}' is not available (is its instrument loaded?)")
        timeout = float(s["timeout"]) if s.get("timeout") else None
        if kind == "wait":
            tools.wait(float(s["seconds"]))
        elif kind == "wait_below":
            tools.wait_below(parameter, float(s["value"]), timeout)
        elif kind == "wait_above":
            tools.wait_above(parameter, float(s["value"]), timeout)
        elif kind == "wait_stable":
            tools.wait_stable(parameter, float(s["tol"]), float(s["dwell"]),
                              float(s["value"]) if s.get("use_target") else None, timeout)
        elif kind == "set":
            history.set(parameter, float(s["value"]))
        elif kind == "repeat_until":
            namespace = {"np": np, "numpy": np, **parameters}
            return "done" if eval(compile(s["expression"], "<condition>", "eval"), namespace) \
                or int(s.get("count", 0)) >= int(s.get("max_repeats", 0)) else "repeat"
    except WaitInterrupted:
        return "stopped"
    return "done"


def python_lines(state):
    """The step as lines of an exported script (the waiting helpers are in the script), or a comment."""
    s = state[STEP_KEY]
    kind, p = s["kind"], s.get("parameter")
    timeout = f", timeout={_g(s['timeout'])}" if s.get("timeout") else ""
    if kind == "wait":
        return [f"wait({_g(s['seconds'])})"]
    if kind == "wait_below":
        return [f"wait_below({p}, {_g(s['value'])}{timeout})"]
    if kind == "wait_above":
        return [f"wait_above({p}, {_g(s['value'])}{timeout})"]
    if kind == "wait_stable":
        target = f", target={_g(s['value'])}" if s.get("use_target") else ""
        return [f"wait_stable({p}, tol={_g(s['tol'])}, dwell={_g(s['dwell'])}{target}{timeout})"]
    if kind == "set":
        return [f"{p}({_g(s['value'])})"]
    return ["# (a 'repeat until' step is not exported: it changes the queue while it runs)"]
