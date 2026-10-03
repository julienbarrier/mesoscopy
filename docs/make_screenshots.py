"""Make the screenshots of the documentation (docs/_static/img/*.png).

The real application is run without a screen (Qt's offscreen platform) on the simulated instruments of
``_static/dummy.station.yaml``: it loads the station, makes a few measurements and takes a picture of each tab and dialog.
Run it from the repository root, with the mesoscopy environment activated:

    python docs/make_screenshots.py

The pictures are made with the offscreen rendering of Qt: they show the program's own widgets, not the look of your system.
"""
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
OUT = os.path.join(HERE, "_static", "img")
os.makedirs(OUT, exist_ok=True)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
app.setStyle("Universal")
WIDTH, HEIGHT = 1500, 880


def pump(seconds=0.1):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def wait(condition, timeout=60):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def shot(widget, name, size=None):
    """Save a picture of ``widget`` as <name>.png."""
    if size:
        widget.resize(*size)
    pump(0.25)
    widget.grab().save(os.path.join(OUT, name + ".png"))
    print("  saved", name)


# no modal window may stop the script: they are recorded, and the ones to show are built and photographed by hand
SHOWN = []
QDialog.exec = lambda self: (SHOWN.append(self), 0)[1]
for _name in ("warning", "information", "critical"):
    setattr(QMessageBox, _name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
MENUS = []
QMenu.exec = lambda self, pos=None: (MENUS.append(self), None)[1]


def menu_shot(menu, name):
    menu.adjustSize()
    menu.grab().save(os.path.join(OUT, name + ".png"))
    print("  saved", name)


# ------------------------------------------------------------------ the application and its folders
from mesoscopy.core.app_settings import AppSettings  # noqa: E402
from mesoscopy.ui.main_window import MainWindow  # noqa: E402

base = tempfile.mkdtemp(prefix="mesoscopy_docs_")
dirs = {name: os.path.join(base, name) for name in ("data", "stations", "logs")}
for folder in dirs.values():
    os.makedirs(folder)
shutil.copy(os.path.join(HERE, "_static", "dummy.station.yaml"), dirs["stations"])
window = MainWindow(AppSettings(os.path.join(base, "settings.ini")))
window.resize(WIDTH, HEIGHT)
window.show()
pump(0.3)
services = window.services
tabs = {"data": window.data_tab_widget, "instruments": window.instruments_tab_widget,
        "explorer": window.parameter_explorer_widget, "measurement": window.sweep_tab_widget,
        "queue": window.queue_widget, "monitor": window.monitor_widget}


def go(tab):
    window.tabs.setCurrentWidget(tabs[tab])
    pump(0.3)


# ------------------------------------------------------------------ Data tab
data = window.data_tab
data.db_folder_display.setText(dirs["data"])
data.populate_database_files()
data.sample_name_input.setText("Test")
data.logs_folder_display.setText(dirs["logs"])
data.start_logging()
pump(0.3)
go("data")
shot(window, "data_tab")

# ------------------------------------------------------------------ Instruments tab
inst = window.instruments_tab
manager = inst.manager
inst.station_folder_display.setText(dirs["stations"])
manager.populate_station_files()
go("instruments")
manager.load_station()
pump(0.4)
shot(window, "instruments_station")
for index in range(inst.instr_list.count()):
    inst.instr_list.item(index).setSelected(True)
inst.load_instr_button.click()
pump(1.0)
wait(lambda: all(manager.health.status.get(n, {}).get("ok") for n in ("dummy_dac", "dummy_dmm")), 15)
inst.connected_instr_list.setCurrentRow(0)
pump(0.5)
shot(window, "instruments_loaded")
inst.instrument_detail._show_page(2)
pump(0.5)
shot(window, "instruments_snapshot")
inst.instrument_detail._show_page(0)
pump(0.4)
shot(window, "instruments_log")

# ------------------------------------------------------------------ Parameter explorer
from mesoscopy.core.experiment_parameters import ParameterDefinition  # noqa: E402
from mesoscopy.ui.tabs.parameter_dialogs import ExperimentParameterDialog  # noqa: E402

registry = services.registry
explorer = window.parameter_explorer_tab
registry.add(ParameterDefinition(name="spectrum", kind="instrument", source=["dummy_scope", "trace"]))
registry.add(ParameterDefinition(name="signal_x2", kind="derived", expression="2 * dummy_dmm_signal", unit="V"))
go("explorer")
explorer.selector.set_path(["dummy_dac"])
explorer.recursive_checkbox.setChecked(True)
pump(0.4)
shot(window, "explorer_tab")
P = registry.parameters
dialog = ExperimentParameterDialog(window, registry, "instrument", definition=registry.definitions["dummy_dac_Vtop"],
                                   source=["dummy_dac", "ch1"], source_text="dummy_dac.ch1", settable=True)
shot(dialog, "dialog_experiment_parameter")
dialog = ExperimentParameterDialog(window, registry, "derived", default_name="gate_sum")
dialog.expression_edit.setText("0.5 * (dummy_dac_Vtop + dummy_dac_Vback)")
shot(dialog, "dialog_derived_parameter")
dialog = ExperimentParameterDialog(window, registry, "trace", source=["dummy_scope", "spectrum"],
                                   source_text="dummy_scope.spectrum", default_name="my_trace")
shot(dialog, "dialog_trace_parameter")
explorer.table.selectRow(0)
MENUS.clear()
explorer._show_browser_menu(explorer.table.visualRect(explorer.table.model().index(0, 1)).center())
if MENUS:
    menu_shot(MENUS[-1], "explorer_menu")

# ------------------------------------------------------------------ Measurement tab: a 1D sweep
from mesoscopy.ui.tabs.measured_box import MeasuredParameterDialog  # noqa: E402

sweep = window.sweep_tab
plot = sweep.plot_panel


def dimension(cls="LinSweep", component="dummy_dac_Vtop", start="-1", stop="1", num=101, delay="0.01", **extra):
    return {"class": cls, "component": [component], "start": start, "stop": stop, "num": num, "delay": delay,
            "array": "np.linspace(0, 1, 11)", "together": [[], []], "together_starts": ["0", "0"],
            "together_stops": ["1", "1"], "get_after_set": False, "actions": [], **extra}


def recipe(name, dimensions, measured=("dummy_dmm_signal",), **extra):
    state = {"experiment_name": "Sweep", "measurement_name": name, "breakout": False, "ramp_to_zero": False,
             "snake": False, "back_and_forth": False, "repeat": {"enabled": False, "times": 1},
             "dimensions": dimensions, "measured": [{"path": [m], "alias": ""} for m in measured], "advanced": {}}
    state.update(extra)
    return state


def run(state, timeout=300):
    sweep.set_state(state)
    pump(0.2)
    finished = []
    services.run.runFinished.connect(finished.append)
    sweep.request_run()
    if not wait(lambda: bool(finished), timeout):
        raise RuntimeError(f"the measurement {state['measurement_name']!r} did not finish in {timeout} s")
    pump(0.6)
    services.run.runFinished.disconnect(finished.append)
    return finished[-1]


go("measurement")
sweep.set_state(recipe("first sweep", [dimension()]))
pump(0.3)
shot(window, "measurement_tab")
dialog = MeasuredParameterDialog(window, registry.parameters(), [])
dialog.selector.set_path(["dummy_dmm_signal"])
shot(dialog, "dialog_measured_parameter")
session = run(recipe("first sweep", [dimension()]))
shot(window, "measurement_1d")
plot.past_spin.setValue(0)
box = sweep.dimension_boxes[0]
box.start_input.setFocus()
sweep._focus_changed(None, box.start_input)
pump(0.3)
shot(window, "measurement_markers")
MENUS.clear()
plot._cursor_x = 0.2
plot._show_plot_menu(plot.canvas.rect().center())
menu_shot(MENUS[-1], "plot_menu")
sweep._focus_changed(None, box.delay_input)
print("part 1 done")

# ------------------------------------------------------------------ Measurement tab: 2D map, together sweep, trace
from mesoscopy.core.dry_run import check_request  # noqa: E402
from qcodes.dataset import load_by_id  # noqa: E402

session = run(recipe("map", [dimension(num=15), dimension(component="dummy_dac_Vback", start="-3", stop="3", num=41,
                                                       delay="0.002")],
                     measured=("dummy_dmm_signal", "dummy_dmm_signal2"), snake=True))
plot.past_spin.setValue(10)
plot.y_combo.setCurrentIndex(plot.y_combo.findData("dummy_dmm_signal"))
pump(0.3)
shot(window, "measurement_2d")

together = dimension(cls="TogetherSweep", num=21)
together["together"] = [["dummy_dac_Vtop"], ["dummy_dac_Vback"]]
together["together_starts"], together["together_stops"] = ["0", "0"], ["1", "2"]
sweep.set_state(recipe("together", [together]))
pump(0.3)
shot(sweep.dimension_boxes[0], "sweep_together")

session = run(recipe("traces", [dimension(start="0", stop="1", num=15, delay="0.005")],
                     measured=("dummy_dmm_signal", "spectrum")))
names = [plot.x_combo.itemData(i) for i in range(plot.x_combo.count())]
trace_axis = next(n for n in names if "frequency" in n)
plot.x_combo.setCurrentIndex(plot.x_combo.findData(trace_axis))
plot.y_combo.setCurrentIndex(plot.y_combo.findData("dummy_scope_trace"))
plot.past_spin.setValue(5)
pump(0.3)
shot(window, "measurement_trace")

# ------------------------------------------------------------------ Check setup and the advanced settings
sweep.set_state(recipe("check", [dimension(start="0", stop="1.5", num=61, delay="0.05")]))
report = check_request(sweep.build_request(), services)
def report_dialog(title, text, width=700):
    """A window like the message of Check setup, with the text wrapped (the offscreen message boxes do not wrap it)."""
    from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout
    dialog = QDialog(window)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(QPushButton("OK"), 0, Qt.AlignmentFlag.AlignRight)
    dialog.setFixedWidth(width)
    dialog.show()
    return dialog


sweep.set_state(recipe("check", [dimension(start="0", stop="1.5", num=61, delay="0.05")]))
report = check_request(sweep.build_request(), services)
shot(report_dialog("Check setup", report.text() or "No problem found."), "dialog_check_setup")
sweep.set_state(recipe("check", [dimension(start="0", stop="5", num=61, delay="0.05")]))
try:
    sweep.build_request()
except ValueError as error:
    shot(report_dialog("Check setup", str(error)), "dialog_check_setup_error")

from PyQt6.QtWidgets import QTabWidget  # noqa: E402
from mesoscopy.ui.tabs.advanced_dialog import AdvancedDialog  # noqa: E402

advanced = {"enter": [{"name": "wait for the gate", "code": "wait_stable(dummy_dac_Vtop, tol=0.01, dwell=10, timeout=600)",
                       "enabled": True}],
            "exit": [{"name": "back to zero", "code": "dummy_dac_Vtop(0)", "enabled": True}],
            "setpoints": ["dummy_dmm_signal2"], "datasets": [], "write_period": None, "use_threads": None,
            "in_memory_cache": None, "log_info": "", "export": True, "export_type": "csv", "export_path": "",
            "save_plot": True, "plot_format": "png"}
axis = dimension()
axis["actions"] = [{"name": "settle", "code": "wait(0.5)", "enabled": True}]
sweep.set_state(recipe("advanced", [axis], advanced=advanced))
parameters = registry.parameters()
dialog = AdvancedDialog(window, sweep.advanced, [(b.get_after_set, b.actions) for b in sweep.dimension_boxes],
                        [b.title() for b in sweep.dimension_boxes],
                        gettable=[n for n, p in parameters.items() if p.gettable],
                        axis_parameters=[["dummy_dac_Vtop"]], measured=["dummy_dmm_signal"],
                        settable=[n for n, p in parameters.items() if p.settable])
dialog.resize(900, 560)
tab_widget = dialog.findChild(QTabWidget)
for index, name in enumerate(("actions", "axes", "datasets", "run_options")):
    tab_widget.setCurrentIndex(index)
    shot(dialog, "advanced_" + name)
tab_widget.setCurrentIndex(0)
dialog.enter_editor._fill_predefined_menu()
menu = dialog.enter_editor.predefined_menu
submenu = [a.menu() for a in menu.actions() if a.menu()][2]
menu_shot(menu, "advanced_predefined")
menu_shot(submenu, "advanced_predefined_parameters")

# ------------------------------------------------------------------ Queue
from mesoscopy.core import queue_steps  # noqa: E402
from mesoscopy.ui.tabs.queue_step_dialogs import SeriesDialog, StepDialog  # noqa: E402

queue = services.queue
sweep.advanced = {}
for name, stop in (("sweep A", "0.5"), ("sweep B", "1")):
    sweep.set_state(recipe(name, [dimension(start="0", stop=stop, num=11, delay="0.01")]))
    sweep.add_to_queue()
queue.insert([queue_steps.new_step("set", parameter="dummy_dac_Vtop", value=0.3),
              queue_steps.new_step("wait_stable", parameter="dummy_dac_Vtop", use_target=True, value=0.3, tol=0.02,
                                   dwell=1.0, timeout=60)], 1)
go("queue")
queue.start()
wait(lambda: not queue.active, 120)
pump(0.5)
sweep.set_state(recipe("sweep C", [dimension(start="0", stop="1.5", num=61, delay="0.1")]))
sweep.add_to_queue()
queue.insert([queue_steps.new_step("wait_below", parameter="dummy_dmm_signal", value=1.0, timeout=600)], 4)
queue.insert([queue_steps.new_step("repeat_until", expression="dummy_dmm_signal() < 1", max_repeats=3)])
qt = window.queue_tab
qt.list.setCurrentRow(2)
pump(0.3)
shot(window, "queue_tab")
readable = [n for n, p in registry.parameters().items() if p.gettable]
settable = [n for n, p in registry.parameters().items() if p.settable]
dialog = StepDialog(window, readable, settable, kind="wait_stable")
dialog.fields["parameter"].setCurrentText("dummy_dac_Vtop")
shot(dialog, "dialog_queue_step")
dialog = SeriesDialog(window, settable, 1)
dialog.parameter.setCurrentText("dummy_dac_Vback")
dialog.start.setValue(-2)
dialog.stop.setValue(2)
shot(dialog, "dialog_queue_series")

# ------------------------------------------------------------------ Monitor and alarms
import math  # noqa: E402

monitor = window.monitor_tab
for name in ("dummy_dmm_signal", "dummy_dac_Vtop", "signal_x2"):
    services.station.add_monitored(registry.parameters()[name])
pump(0.5)
go("monitor")
vtop = registry.parameters()["dummy_dac_Vtop"]
for step in range(24):
    vtop(round(1.2 * math.sin(step / 3.0), 3))
    monitor.poll(background=False)
    wait(lambda: not monitor._polling, 10)
    pump(0.15)
now = time.time()
for key, history in monitor._history.items():  # the readings were made in a few seconds: spread them over ten minutes
    points = list(history)
    history.clear()
    for index, (_, value) in enumerate(points):
        history.append((now - (len(points) - 1 - index) * 25.0, value))
monitor._redraw_traces()
alarm_parameter = registry.parameters()["dummy_dac_Vtop"]
services.alarms.add(alarm_parameter)
services.alarms._check(alarm_parameter, 1.95)
pump(0.5)
shot(window, "monitor_tab")

# ------------------------------------------------------------------ Data tab: the explorer
from mesoscopy.ui.tabs.compare_dialogs import ComparePickerDialog  # noqa: E402
from mesoscopy.ui.tabs.log_viewer import LogViewerDialog  # noqa: E402

go("data")
data.refresh_experiments()
pump(0.4)
data.experiment_combo.setCurrentIndex(0)
data.on_experiment_changed()
pump(0.5)
rows = data.runs_table.rowCount()
data.set_run_tag(0, "green")
data.set_run_tag(min(2, rows - 1), "red")
data._write_run_metadata(min(2, rows - 1), "notes", "gate looked leaky above 1 V",
                         __import__("mesoscopy.core.run_tags", fromlist=["x"]).set_notes)
data.runs_table.selectRow(1)
data.on_run_selected()
pump(0.4)
shot(window, "data_explorer")
menu = data.build_run_menu(1)
menu_shot(menu, "data_run_menu")
dialog = LogViewerDialog(window, dirs["logs"], list(services.station.instruments()))
shot(dialog, "data_log_viewer", (1000, 520))
dialog = ComparePickerDialog(window, folder=dirs["data"], db_name=os.path.basename(services.data.selected_file))
shot(dialog, "dialog_compare_runs")

# ------------------------------------------------------------------ Settings and About
from mesoscopy.ui.about_dialog import AboutDialog  # noqa: E402
from mesoscopy.ui.settings_dialog import SettingsDialog  # noqa: E402

dialog = SettingsDialog(window, services.settings, window.save_session)
for index in range(dialog.tabs.count()):
    dialog.tabs.setCurrentIndex(index)
    label = dialog.tabs.tabText(index).lower().replace(" ", "_")
    shot(dialog, "settings_" + label, (760, 560))
dialog = AboutDialog(window, services.settings.file_name())
shot(dialog, "about")
print("all done")
