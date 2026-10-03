"""Pre-defined actions: one line each, chosen from a menu in the Advanced settings (no Qt).

An entry says what it needs from the user (an experiment parameter to read or to set, picked from a drop-down) and the
single line of code it puts in the action, with the numbers to adapt. They are ordinary actions afterwards: the code
can be edited, and several can be combined with code of your own.
"""
from dataclasses import dataclass

from mesoscopy.core.dond_options import new_action


@dataclass(frozen=True)
class Predefined:
    key: str
    label: str        # in the menu
    needs: str        # "" (no parameter), "get" (a readable parameter) or "set" (a settable one)
    code: str         # one line; {p} is the parameter
    name: str         # of the action in the list; {p} is the parameter


PREDEFINED = (
    Predefined("wait", "Wait a fixed time", "", "wait(60)", "wait 60 s"),
    Predefined("below", "Wait until a parameter is below...", "get", "wait_below({p}, 4.5, timeout=3600)", "wait {p} below"),
    Predefined("above", "Wait until a parameter is above...", "get", "wait_above({p}, 0, timeout=3600)", "wait {p} above"),
    Predefined("stable", "Wait until a parameter is stable...", "get",
               "wait_stable({p}, tol=0.02, dwell=60, timeout=3600)", "wait {p} stable"),
    Predefined("target", "Wait until a parameter has reached a value and is stable...", "get",
               "wait_stable({p}, target=0, tol=0.01, dwell=30, timeout=3600)", "wait {p} at target"),
    Predefined("set", "Set a parameter to a value...", "set", "{p}(0)", "set {p}"),
)


def build_action(entry, parameter=""):
    """The action (``new_action`` dict) of a pre-defined entry for ``parameter``."""
    return new_action(entry.name.format(p=parameter), entry.code.format(p=parameter))
