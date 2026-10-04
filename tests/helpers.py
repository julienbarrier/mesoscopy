"""Small helpers shared by the tests: waiting on the Qt event loop, and recipes of the Measurement tab."""
import time

from PyQt6.QtWidgets import QApplication


def pump(seconds=0.05):
    end = time.time() + seconds
    app = QApplication.instance()
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def wait(condition, timeout=60):
    """Process events until ``condition()`` is true; returns whether it became true in time."""
    app = QApplication.instance()
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return bool(condition())


def dimension(cls="LinSweep", component="dummy_dac_Vtop", start="0", stop="0.5", num=6, delay="0.01", **extra):
    """One axis of a recipe, as ``SweepDimensionBox.get_state()`` gives it."""
    return {"class": cls, "component": [component], "start": start, "stop": stop, "num": num, "delay": delay,
            "array": "np.linspace(0, 1, 5)", "together": [[], []], "together_starts": ["0", "0"],
            "together_stops": ["1", "1"], "get_after_set": False, "actions": [], **extra}


def recipe(name, dimensions, measured=("dummy_dmm_signal",), **extra):
    """The state of the Measurement tab (``SweepTab.get_state()``) for a measurement."""
    state = {"experiment_name": "exp", "measurement_name": name, "breakout": False, "ramp_to_zero": False,
             "snake": False, "back_and_forth": False, "repeat": {"enabled": False, "times": 1},
             "dimensions": dimensions, "measured": [{"path": [m], "alias": ""} for m in measured], "advanced": {}}
    state.update(extra)
    return state
