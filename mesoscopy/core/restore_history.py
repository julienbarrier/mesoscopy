"""Setting parameters in a way that can be undone: "Restore previous value" (no Qt).

QCoDeS' ``parameter.set_to(value)`` sets a parameter and puts the old value back when its ``with`` block ends. The
application cannot keep a ``with`` block open while the user does something else, so the context manager is entered
by hand and kept: leaving it later is the restore. Every parameter has a stack of them: each set adds one, and
"Restore previous value" leaves the latest, going back one step at a time.
"""
import math
import threading


def _same(a, b):
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return a == b


class RestoreHistory:
    def __init__(self):
        self._lock = threading.Lock()
        self._stacks = {}  # id(parameter) -> [(previous value, context manager)]
        self._touched = set()  # id(parameter) of the parameters the application has set: the ones to bring to 0 at the end

    def set(self, parameter, value):
        """Set ``parameter`` to ``value`` (validators, step and inter-delay apply), remembering the value it had.

        Meant for a job thread: the set can ramp for a long time. The parameter must be readable (its previous value
        is read); a parameter that cannot be read is simply set, and cannot be restored."""
        self.mark_touched(parameter)
        if not parameter.gettable:
            parameter.set(value)
            return
        context = parameter.set_to(value, allow_changes=True)
        previous = parameter.cache()  # what set_to puts back
        context.__enter__()           # sets the value
        with self._lock:
            self._stacks.setdefault(id(parameter), []).append((previous, context))

    def mark_touched(self, parameter):
        """The application is about to change ``parameter`` (a set, or a sweep): it will have to be brought back to 0."""
        with self._lock:
            self._touched.add(id(parameter))

    def was_touched(self, parameter):
        with self._lock:
            return id(parameter) in self._touched

    def has_previous(self, parameter):
        with self._lock:
            return bool(self._stacks.get(id(parameter)))

    def previous_value(self, parameter):
        """The value "Restore previous value" would set (None if there is none)."""
        with self._lock:
            stack = self._stacks.get(id(parameter))
            return stack[-1][0] if stack else None

    def restore(self, parameter):
        """Put back the value the parameter had before the last set of the history. Returns it.

        Raises ValueError if there is nothing to restore, RuntimeError if the value could not be put back."""
        with self._lock:
            stack = self._stacks.get(id(parameter))
            if not stack:
                raise ValueError(f"{parameter.full_name} has no previous value to restore.")
            previous, context = stack.pop()
        context.__exit__(None, None, None)  # sets the old value back (it logs, but does not raise, if that fails)
        if not _same(parameter.cache(), previous):
            raise RuntimeError(f"{parameter.full_name} could not be set back to {previous!r}.")
        return previous

    def clear(self):
        with self._lock:
            self._stacks.clear()
            self._touched.clear()
