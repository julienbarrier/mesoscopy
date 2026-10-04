"""Fixtures of the tests.

The application tests drive the real main window, without a screen (Qt's offscreen platform), on the simulated
instruments of ``docs/_static/dummy.station.yaml``. QCoDeS instruments are global, so the window and the station are made once
per session; the tests of ``test_app.py`` run in the order of the file and share what the earlier ones did (the runs in the
database, for instance).
"""
import os
import shutil
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
from PyQt6.QtWidgets import QDialog, QFileDialog, QMenu, QMessageBox  # noqa: E402

from helpers import pump, wait  # noqa: E402


@pytest.fixture(scope="session")
def blocked_windows():
    """No modal window may stop a test: message boxes answer at once, dialogs are recorded and not run, menus are recorded."""
    patcher = pytest.MonkeyPatch()
    shown = SimpleNamespace(dialogs=[], menus=[])
    for name in ("warning", "information", "critical"):
        patcher.setattr(QMessageBox, name,
                        staticmethod(lambda *a, _n=name, **k: (shown.dialogs.append((_n, a[1:3])), QMessageBox.StandardButton.Ok)[1]))
    patcher.setattr(QMessageBox, "question",
                    staticmethod(lambda *a, **k: (shown.dialogs.append(("question", a[1:3])), QMessageBox.StandardButton.Yes)[1]))
    patcher.setattr(QDialog, "exec", lambda self: (shown.dialogs.append(("exec", type(self).__name__)), 0)[1])
    patcher.setattr(QMenu, "exec", lambda self, pos=None: (shown.menus.append(self), None)[1])
    yield shown
    patcher.undo()


@pytest.fixture(scope="session")
def app(qapp, blocked_windows, tmp_path_factory):
    """The main window with the dummy station loaded and its three instruments connected."""
    from mesoscopy.core.app_settings import AppSettings
    from mesoscopy.ui.main_window import MainWindow

    base = tmp_path_factory.mktemp("mesoscopy")
    dirs = {name: str(base / name) for name in ("data", "stations", "logs")}
    for folder in dirs.values():
        os.makedirs(folder)
    shutil.copy(os.path.join(ROOT, "docs", "_static", "dummy.station.yaml"), dirs["stations"])
    window = MainWindow(AppSettings(str(base / "settings.ini")))
    window.resize(1400, 860)
    window.show()
    pump(0.3)
    ctx = SimpleNamespace(window=window, services=window.services, dirs=dirs, shown=blocked_windows, base=str(base))
    data, instruments = window.data_tab, window.instruments_tab
    data.db_folder_display.setText(dirs["data"])
    data.populate_database_files()
    data.sample_name_input.setText("Test")
    data.logs_folder_display.setText(dirs["logs"])
    instruments.station_folder_display.setText(dirs["stations"])
    instruments.manager.populate_station_files()
    assert instruments.manager.load_station()
    pump(0.3)
    for index in range(instruments.instr_list.count()):
        instruments.instr_list.item(index).setSelected(True)
    instruments.load_instr_button.click()
    assert wait(lambda: instruments.connected_instr_list.count() >= 3, 30)
    pump(0.5)
    yield ctx
    window.close()
    pump(0.3)
    # leave QCoDeS as it was found: its default station would otherwise be snapshotted by the measurements of other tests
    from qcodes.instrument import Instrument
    from qcodes.station import Station

    Station.default = None
    Instrument.close_all()


def pytest_collection_modifyitems(items):
    """The application tests share one window and the QCoDeS global station: run them last."""
    items.sort(key=lambda item: item.fspath.basename == "test_app.py")
