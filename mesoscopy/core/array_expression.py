"""Evaluate user-typed Python expressions into sweep arrays (no Qt)."""
import builtins

import numpy as np

# Small set of builtins for typing arrays by hand; numpy is available as ``np``.
_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "enumerate", "float", "int", "len", "list", "map", "max",
    "min", "range", "reversed", "round", "sorted", "sum", "tuple", "zip",
)
_NAMESPACE = {
    "__builtins__": {name: getattr(builtins, name) for name in _BUILTIN_NAMES},
    "np": np,
    "numpy": np,
}


def evaluate_array_expression(text):
    """
    Evaluate a Python expression (numpy available as ``np``) into a 1-D float array, e.g.
    ``np.concatenate((np.linspace(0, 1, 51), np.linspace(1, 0, 51)))``.

    The expression is run with ``eval``: this is meant for the user's own input in the
    local application, it is not a security sandbox.
    Raises ValueError with a readable message if the result is not a usable sweep array.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("The array expression is empty.")
    try:
        value = eval(text, dict(_NAMESPACE))
    except Exception as e:
        raise ValueError(f"Cannot evaluate the array expression: {type(e).__name__}: {e}") from e
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError("The array expression must give numbers.") from e
    if array.ndim != 1:
        raise ValueError(f"The array expression must give a 1-D array (got shape {array.shape}).")
    if array.size == 0:
        raise ValueError("The array expression gave an empty array.")
    if not np.all(np.isfinite(array)):
        raise ValueError("The array contains NaN or infinite values.")
    return array
