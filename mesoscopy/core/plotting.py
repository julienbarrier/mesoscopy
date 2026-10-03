"""Plotting helpers used by experiment and measurement UI (MplCanvas, LivePlottingSubscriber)."""
import matplotlib
matplotlib.use('QtAgg')
import numpy as np
from cycler import cycler
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal

# colour-blind friendly (Okabe-Ito), blue first: 'C0' is the default colour, 'C1' the second (orange)
COLORBLIND_CYCLE = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000")
matplotlib.rcParams["axes.prop_cycle"] = cycler(color=COLORBLIND_CYCLE)


DRAG_PIXELS = 6  # a press that moves less than this is a click


class MplCanvas(FigureCanvas):
    """A matplotlib canvas with one axes. Over the axes the mouse cursor is a cross (to pick out the features of a
    curve) and ``cursorMoved(x, y)`` gives the position in data coordinates; ``cursorLeft`` when it leaves the axes."""

    cursorMoved = pyqtSignal(float, float)
    cursorLeft = pyqtSignal()
    clicked = pyqtSignal(float, float)  # left click over the axes: x and y in data coordinates
    dragged = pyqtSignal(float, float)  # left button dragged sideways over the axes: x where it went down, x where it came up

    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)
        self.mpl_connect("axes_enter_event", self._on_enter)
        self.mpl_connect("axes_leave_event", self._on_leave)
        self.mpl_connect("motion_notify_event", self._on_motion)
        self.mpl_connect("button_press_event", self._on_press)
        self.mpl_connect("button_release_event", self._on_release)
        self._press = None  # (x data, y data, x pixel) where the left button went down
        self._last_x = None  # last x (data) of the pointer over the axes while the button is down
        self._span = None

    def _on_enter(self, _event):
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _on_leave(self, _event):
        self.unsetCursor()
        self.cursorLeft.emit()

    def _on_press(self, event):
        if event.button == 1 and not event.dblclick and event.inaxes is self.axes \
                and event.xdata is not None and event.ydata is not None:
            self._press, self._last_x = (float(event.xdata), float(event.ydata), float(event.x)), float(event.xdata)

    def _on_release(self, event):
        press, self._press = self._press, None
        self._clear_span()
        if press is None or event.button != 1:
            return
        x0, y0, pixel0 = press
        x1 = float(event.xdata) if event.inaxes is self.axes and event.xdata is not None else self._last_x
        if x1 is not None and abs(float(event.x) - pixel0) > DRAG_PIXELS:
            self.dragged.emit(x0, x1)
        else:
            self.clicked.emit(x0, y0)

    def _clear_span(self):
        if self._span is not None:
            try:
                self._span.remove()
            except Exception:
                pass  # the axes were cleared meanwhile
            self._span = None
            self.draw_idle()

    def _show_span(self, x0, x1):
        if self._span is not None:
            try:
                self._span.remove()
            except Exception:
                pass
        self._span = self.axes.axvspan(min(x0, x1), max(x0, x1), color="C1", alpha=0.2)
        self.draw_idle()

    def _on_motion(self, event):
        if self._press is not None and event.inaxes is self.axes and event.xdata is not None:
            self._last_x = float(event.xdata)
            if abs(float(event.x) - self._press[2]) > DRAG_PIXELS:
                self._show_span(self._press[0], self._last_x)
        if event.inaxes is self.axes and event.xdata is not None and event.ydata is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.cursorMoved.emit(float(event.xdata), float(event.ydata))


class LivePlottingSubscriber:
    def __init__(self, canvas, x_dim, y_dim=1):
        self.canvas = canvas
        self.is_2d = y_dim > 1
        self.x_dim = x_dim
        self.y_dim = y_dim
        if self.is_2d:
            self.x_data = np.zeros((x_dim, y_dim))
            self.y_data = np.zeros((x_dim, y_dim))
            self.z_data = np.zeros((x_dim, y_dim))
            self.i = 0
            self.j = 0
        else:
            self.x_data = []
            self.y_data = []

    def __call__(self, result_list):
        if self.is_2d:
            if self.i < self.x_dim and self.j < self.y_dim:
                self.x_data[self.i, self.j] = result_list[0]
                self.y_data[self.i, self.j] = result_list[1]
                self.z_data[self.i, self.j] = result_list[2]

                self.j += 1
                if self.j == self.y_dim:
                    self.j = 0
                    self.i += 1

                if self.j == 0:
                    self.update_plot()
        else:
            if len(result_list) >= 2:
                self.x_data.append(result_list[0])
                self.y_data.append(result_list[1])
                self.update_plot()

    def update_plot(self):
        self.canvas.axes.cla()
        if self.is_2d:
            self.canvas.axes.pcolormesh(self.x_data, self.y_data, self.z_data, shading='auto')
        else:
            self.canvas.axes.plot(self.x_data, self.y_data, '.-')
        self.canvas.draw()
