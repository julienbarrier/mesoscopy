"""Helpers to inspect, read, set and monitor QCoDeS parameters (no Qt)."""
import ast
from datetime import datetime

import numpy as np
from qcodes.instrument import InstrumentBase
from qcodes.instrument.channel import ChannelTuple
from qcodes.monitor.monitor import _get_metadata
from qcodes.parameters import GroupParameter, ParameterBase

MAX_PARAMETERS = 300  # rows listed when a whole instrument is inspected


def get_children(component):
    """Return {name: child} for the sub-components of ``component``.

    Parameters are leaves and have no children. Instruments and modules expose
    their submodules (channels, channel lists, ...) and parameters. A channel
    list is expanded into its channels.
    """
    if isinstance(component, ParameterBase):
        return {}
    if isinstance(component, ChannelTuple):
        return {ch.short_name: ch for ch in component}
    if isinstance(component, InstrumentBase):
        children = dict(component.submodules)
        children.update(component.parameters)
        return children
    return {}


def group_members(parameter):
    """The parameters sharing one instrument command with ``parameter`` (itself included), in a stable order.

    A ``GroupParameter`` is read and set together with the others of its group, so they form one unit.
    Any other parameter is a group of one."""
    group = getattr(parameter, "group", None) if isinstance(parameter, GroupParameter) else None
    if group is None:
        return [parameter]
    return sorted(group.parameters.values(), key=lambda p: p.full_name)


def collect_parameters(component, path=(), recursive=False, limit=MAX_PARAMETERS):
    """Parameters of ``component`` as ([(path, parameter)] sorted by full name, truncated flag).

    ``path`` is the component's own path (names from the station root); each result carries the
    path of its parameter. A parameter gives itself. An instrument, channel or module gives the
    parameters directly under it, or all those below it when ``recursive`` is true. At most
    ``limit`` are returned.
    """
    if isinstance(component, ParameterBase):
        return [(tuple(path), component)], False
    found, seen = [], set()

    def walk(node, node_path):
        for name, child in get_children(node).items():
            if isinstance(child, ParameterBase):
                if id(child) not in seen:
                    seen.add(id(child))
                    found.append((tuple(node_path) + (name,), child))
            elif recursive:
                walk(child, tuple(node_path) + (name,))

    walk(component, tuple(path))
    # group members stay together, ordered by the group's first member
    found.sort(key=lambda item: (group_members(item[1])[0].full_name, item[1].full_name))
    return found[:limit], len(found) > limit


def zhinst_node_is_read_only(parameter):
    """True for zhinst-qcodes parameters whose device node is not writable.

    zhinst reports every node as settable, so the node info of the underlying
    zhinst-toolkit node is consulted. Other drivers have no such node (False).
    """
    tk_node = getattr(parameter, "_tk_node", None)
    if tk_node is None:
        return False
    try:
        return tk_node.node_info.writable is False
    except Exception:
        return False


def cached_value(parameter):
    """Last known value without talking to the instrument (None if there is none)."""
    try:
        return parameter.cache.get(get_if_invalid=False)
    except Exception:
        return None


def format_value(value):
    """Short text for a parameter value."""
    if value is None:
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (float, np.floating)):
        return f"{value:.6g}"
    if isinstance(value, np.ndarray):
        return f"array{value.shape}"
    return str(value)


def parse_value(text, parameter):
    """Turn what was typed into a value for ``parameter``: numbers, True/False, lists... or plain text.

    Raises ValueError if the field is empty.
    """
    text = text.strip()
    if not text:
        raise ValueError("Enter a value to set.")
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text  # e.g. a string for an Enum or Strings validator


def _joined(parameter, single, plural):
    """``label``/``unit`` of a parameter, or the joined ``labels``/``units`` of a multi-parameter."""
    value = getattr(parameter, single, None)
    if value:
        return str(value)
    many = getattr(parameter, plural, None)
    return ", ".join(str(v) for v in many) if many else ""


def parameter_label(parameter):
    return _joined(parameter, "label", "labels")


def parameter_unit(parameter):
    return _joined(parameter, "unit", "units")


def describe_validator(parameter):
    vals = getattr(parameter, "vals", None)
    return str(vals) if vals is not None else "—"


def describe_step(parameter):
    step = getattr(parameter, "step", None)
    return f"{step:g}" if step else "—"


def describe_inter_delay(parameter):
    delay = getattr(parameter, "inter_delay", None)
    return f"{delay:g} s" if delay else "—"


def read_for_monitor(parameter):
    """Read ``parameter`` from the instrument and describe it as the QCoDeS monitor does.

    ``parameter.get()`` makes the reading live; ``qcodes.monitor``'s metadata helper then gives
    the name, unit and timestamp. Returns a dict with: value (raw), numeric (float or None),
    text, name, unit, ts (epoch seconds).
    """
    return describe_for_monitor(parameter, parameter.get())


def latest_for_monitor(parameter):
    """The last value QCoDeS holds for ``parameter`` (nothing is read from the instrument), described like
    ``read_for_monitor``; None when it holds none yet."""
    value = parameter.get_latest()
    return None if value is None else describe_for_monitor(parameter, value)


def source_chain_ids(parameters):
    """ids of ``parameters`` and of what each is a delegate of: setting or reading a delegate updates the cache of its
    source too, so their last values are current."""
    ids = set()
    for parameter in parameters:
        while parameter is not None and id(parameter) not in ids:
            ids.add(id(parameter))
            parameter = getattr(parameter, "source", None)
    return ids


def describe_for_monitor(parameter, value):
    """``value`` of ``parameter`` described as the QCoDeS monitor does (see ``read_for_monitor``)."""
    meta = _get_metadata(parameter)["parameters"][0]["parameters"][0]
    numeric = None
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)):
        numeric = float(value)
    return {
        "value": value,
        "numeric": numeric,
        "text": format_value(value),
        "name": meta["name"],
        "unit": meta["unit"] or "",
        "ts": meta["ts"] if meta["ts"] is not None else datetime.now().timestamp(),
    }
