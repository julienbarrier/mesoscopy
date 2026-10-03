"""The ``dond`` options behind the Measurement tab's "Advanced settings" (no Qt).

What is kept, as plain data (``default_advanced()``), in the state of the Measurement tab:

* ``enter`` / ``exit``: lists of actions run before the measurement starts / after it ends (dond ``enter_actions`` and
  ``exit_actions``);
* ``setpoints``: names of experiment parameters recorded as additional setpoints (dond ``additional_setpoints``: read
  once before the sweep, stored with every point);
* ``datasets``: ``[{"name", "setpoints": [...], "measured": [...]}]`` to write several datasets (dond
  ``dataset_dependencies``); empty: one dataset;
* ``write_period`` (s), ``use_threads``, ``in_memory_cache`` (None: the default), ``log_info``;
* per-run auto-actions (``core/auto_actions``): ``export`` (None: as the QCoDeS configuration says, True / False: this
  run exports its data / does not), ``export_type`` ("csv" / "netcdf"; "": the configured one), ``export_path`` ("": the
  configured folder), ``save_plot`` (save the plots of the run with ``plot_dataset``) and ``plot_format``.

And, in the state of each axis, ``get_after_set`` and ``actions`` (dond sweep ``post_actions``: run right after the axis
parameter is set, before its delay and before the inner loop).

An action is ``{"name", "code", "enabled"}``: Python statements, run with ``exec`` in a namespace that holds the
experiment parameters by name, ``np``, ``time``, ``station`` and ``const``. It is the user's own code in the local
application, not a sandbox.
"""
import ast
import builtins
import copy
import time
from dataclasses import dataclass, field

import numpy as np
from qcodes.dataset.dond.do_nd_utils import BreakConditionInterrupt
from scipy import constants as const

from mesoscopy.core.auto_actions import EXPORT_TYPES, PLOT_FORMATS
from mesoscopy.core.wait_tools import WaitInterrupted


def new_action(name="action", code="", enabled=True):
    return {"name": name, "code": code, "enabled": bool(enabled)}


def default_advanced():
    return {"enter": [], "exit": [], "setpoints": [], "datasets": [], "write_period": None, "use_threads": None,
            "in_memory_cache": None, "log_info": "", "export": None, "export_type": "", "export_path": "",
            "save_plot": False, "plot_format": "png"}


def clean_actions(items):
    """Actions from saved data: only well-formed entries, with all their keys."""
    return [new_action(str(a.get("name") or "action"), str(a.get("code") or ""), a.get("enabled", True))
            for a in items or [] if isinstance(a, dict)]


def _optional(value, kind):
    if value is None or value == "":
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        return None


def normalise_advanced(data):
    """``data`` (maybe missing, maybe from an older version) as a complete advanced-settings dict."""
    data = data if isinstance(data, dict) else {}
    result = default_advanced()
    result["enter"] = clean_actions(data.get("enter"))
    result["exit"] = clean_actions(data.get("exit"))
    result["setpoints"] = [str(n) for n in data.get("setpoints") or []]
    result["datasets"] = [
        {"name": str(d.get("name") or ""), "setpoints": [str(n) for n in d.get("setpoints") or []],
         "measured": [str(n) for n in d.get("measured") or []]}
        for d in data.get("datasets") or [] if isinstance(d, dict)
    ]
    period = _optional(data.get("write_period"), float)
    result["write_period"] = period if period and period > 0 else None
    result["use_threads"] = _optional(data.get("use_threads"), bool)
    result["in_memory_cache"] = _optional(data.get("in_memory_cache"), bool)
    result["log_info"] = str(data.get("log_info") or "")
    result["export"] = _optional(data.get("export"), bool)
    result["export_type"] = data.get("export_type") if data.get("export_type") in EXPORT_TYPES else ""
    result["export_path"] = str(data.get("export_path") or "").strip()
    result["save_plot"] = bool(data.get("save_plot", False))
    result["plot_format"] = data.get("plot_format") if data.get("plot_format") in PLOT_FORMATS else "png"
    return result


def describe_changes(advanced, axes=()):
    """What differs from the defaults, as short phrases (the button's label and tooltip, the recipe description).

    ``axes``: [(get_after_set, actions)] outermost first."""
    items = []
    count = lambda actions: len([a for a in actions if a.get("enabled", True)])
    if count(advanced["enter"]):
        items.append(f"{count(advanced['enter'])} action(s) before the measurement")
    if count(advanced["exit"]):
        items.append(f"{count(advanced['exit'])} action(s) after the measurement")
    for index, (get_after_set, actions) in enumerate(axes, start=1):
        if get_after_set:
            items.append(f"axis {index}: read back after setting")
        if count(actions):
            items.append(f"axis {index}: {count(actions)} action(s) after each point")
    if advanced["setpoints"]:
        items.append("additional setpoints: " + ", ".join(advanced["setpoints"]))
    if advanced["datasets"]:
        items.append(f"{len(advanced['datasets'])} datasets: " + ", ".join(d["name"] for d in advanced["datasets"]))
    if advanced["write_period"] is not None:
        items.append(f"write period {advanced['write_period']:g} s")
    if advanced["use_threads"] is not None:
        items.append("threads " + ("on" if advanced["use_threads"] else "off"))
    if advanced["export"] is not None:
        where = f" to {advanced['export_path']}" if advanced["export_path"] else ""
        items.append(("export the data after the run" + (f" ({advanced['export_type']})" if advanced["export_type"] else "") + where)
                     if advanced["export"] else "no automatic export")
    if advanced["save_plot"]:
        items.append(f"save the plots after the run ({advanced['plot_format']})")
    if advanced["in_memory_cache"] is not None:
        items.append("in-memory cache " + ("on" if advanced["in_memory_cache"] else "off"))
    if advanced["log_info"].strip():
        items.append("log message")
    return items


# ================= actions =================
def build_namespace(parameters, station, tools=None):
    """The names an action can use: the experiment parameters ({name: parameter}), ``station``, ``np``, ``time``,
    ``const`` and, with ``tools`` (a ``WaitTools``), the waiting helpers (``wait``, ``wait_until``, ``wait_below``,
    ``wait_above``, ``wait_stable``). One dict per run: the actions of the run share it (an enter action can define what
    later ones use)."""
    namespace = {"__builtins__": builtins, "np": np, "numpy": np, "time": time, "const": const, "station": station}
    if tools is not None:
        namespace.update(tools.functions())
    namespace.update(parameters)
    return namespace


def compile_action(action, where):
    """The code object of an action. Raises ValueError("Action 'name' (where), line N: ...") on a syntax error."""
    try:
        return compile(action["code"], f"<action {action['name']}>", "exec")
    except SyntaxError as e:
        raise ValueError(f"Action '{action['name']}' ({where}), line {e.lineno}: {e.msg}") from None


def make_callable(action, where, namespace):
    """A function without arguments for dond that runs the action in ``namespace``. An error in it is raised with
    the action's name."""
    code = compile_action(action, where)
    name = action["name"]

    def run():
        try:
            exec(code, namespace)
        except WaitInterrupted as e:  # Stop was pressed while the action waited: the run ends cleanly, as after a Stop
            raise BreakConditionInterrupt(str(e)) from e
        except Exception as e:
            raise RuntimeError(f"Action '{name}' ({where}) failed: {type(e).__name__}: {e}") from e

    return run


def make_callables(actions, where, namespace):
    return [make_callable(a, where, namespace) for a in actions if a.get("enabled", True)]


def names_used(actions):
    """Names that appear in the code of the actions (to know which experiment parameters they use)."""
    names = set()
    for action in actions:
        try:
            tree = ast.parse(action.get("code", ""))
        except SyntaxError:
            continue
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names


# ================= validation =================
def validate_datasets(datasets, axes, extra, measured):
    """None if the datasets can be written, else why not (in words).

    ``axes``: for each swept axis, the names of its parameters (several for a TogetherSweep); ``extra``: names of the
    additional setpoints; ``measured``: dataset names of the measured parameters. dond wants each measured parameter in
    a dataset, and each dataset to depend on at least one parameter of every dimension (every axis, and every
    additional setpoint, which dond counts as a dimension)."""
    if not datasets:
        return None
    names = [d["name"].strip() for d in datasets]
    if any(not n for n in names):
        return "Every dataset needs a name."
    if len(set(names)) != len(names):
        return "Dataset names must be different."
    for d, name in zip(datasets, names):
        if not [m for m in d["measured"] if m in measured]:
            return f"Dataset '{name}' has no measured parameter."
        for index, parameters in enumerate(axes, start=1):
            if not set(parameters) & set(d["setpoints"]):
                return f"Dataset '{name}' must depend on axis {index}."
        for parameter in extra:
            if parameter not in d["setpoints"]:
                return f"Dataset '{name}' must depend on the additional setpoint '{parameter}'."
    used = {m for d in datasets for m in d["measured"]}
    missing = [m for m in measured if m not in used]
    if missing:
        return f"The measured parameter '{missing[0]}' is in no dataset."
    return None


# ================= what a run needs =================
@dataclass
class DondOptions:
    """The options of one run, ready for dond (the actions are callables, the datasets still refer to names)."""
    enter_actions: list = field(default_factory=list)
    exit_actions: list = field(default_factory=list)
    additional_setpoints: list = field(default_factory=list)   # [(name, parameter)]
    datasets: list = field(default_factory=list)               # [{"name", "setpoints", "measured"}]
    write_period: float = None
    use_threads: bool = None
    in_memory_cache: bool = None
    log_info: str = ""
    export: bool = None
    export_type: str = ""
    export_path: str = ""
    save_plot: bool = False
    plot_format: str = "png"

    @property
    def dataset_names(self):
        return [d["name"].strip() for d in self.datasets]


def build_options(advanced, parameters, namespace):
    """The ``DondOptions`` of the advanced settings. ``parameters``: the available experiment parameters. Raises
    ValueError with a readable message (a syntax error in an action, an unavailable or unreadable setpoint)."""
    advanced = normalise_advanced(advanced)
    extra = []
    for name in advanced["setpoints"]:
        parameter = parameters.get(name)
        if parameter is None or not getattr(parameter, "gettable", False):
            raise ValueError(f"The additional setpoint '{name}' is not available: connect its instrument or "
                             "remove it in the advanced settings.")
        extra.append((name, parameter))
    return DondOptions(
        enter_actions=make_callables(advanced["enter"], "before the measurement", namespace),
        exit_actions=make_callables(advanced["exit"], "after the measurement", namespace),
        additional_setpoints=extra, datasets=copy.deepcopy(advanced["datasets"]),
        write_period=advanced["write_period"], use_threads=advanced["use_threads"],
        in_memory_cache=advanced["in_memory_cache"], log_info=advanced["log_info"].strip(),
        export=advanced["export"], export_type=advanced["export_type"], export_path=advanced["export_path"],
        save_plot=advanced["save_plot"], plot_format=advanced["plot_format"],
    )


def check_run(options, swept, measured_names):
    """Raise ValueError for what dond would refuse: an additional setpoint that is also swept, datasets that do not
    fit the axes. ``swept``: for each axis, the names of the experiment parameters it sets."""
    swept_names = {n for axis in swept for n in axis}
    for name, _ in options.additional_setpoints:
        if name in swept_names:
            raise ValueError(f"'{name}' is swept: it cannot also be an additional setpoint.")
    error = validate_datasets(options.datasets, swept, [n for n, _ in options.additional_setpoints], measured_names)
    if error:
        raise ValueError(error)


def run_names(measurement_name, options, repetition_suffix=""):
    """The names the datasets of a run get: the measurement name alone, or with each dataset's name."""
    if not options.datasets:
        return [f"{measurement_name}{repetition_suffix}"]
    return [f"{measurement_name} - {name}{repetition_suffix}" for name in options.dataset_names]
