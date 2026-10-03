"""Sparklines of the monitored parameters in the status bar."""
import time

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from mesoscopy.core.plot_math import decimate


# Colours of the sparklines: the Okabe-Ito palette, chosen to be told apart with the common kinds of colour blindness
# (yellow and black left out: yellow vanishes on a light background, black on a dark one). A parameter keeps its colour
# as long as its place in the Monitor table does not change.
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#A6761D", "#8C8C8C")


def sparkline_color(slot):
    return QColor(COLORS[slot % len(COLORS)])


class Sparkline(QWidget):
    """A small trace of one parameter over a duration: the line, then the parameter's name on its right in the same
    colour. No axis, no scale: the last value and the range are in the tooltip."""

    LINE_WIDTH, NAME_WIDTH, HEIGHT = 86, 64, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.LINE_WIDTH + self.NAME_WIDTH + 6, self.HEIGHT)
        self._name, self._unit, self._points, self._window_s = "", "", [], 600
        self._color = sparkline_color(0)

    def set_series(self, name, unit, points, window_s, slot=0):
        self._name, self._unit, self._points, self._window_s = name, unit, list(points), window_s
        self._color = sparkline_color(slot)
        self.setToolTip(self._tooltip())
        self.update()

    def _visible(self, now):
        """Points inside the duration as (x fraction 0..1 with 1 = now, value)."""
        return [(1 - (now - ts) / self._window_s, value) for ts, value in self._points if now - ts <= self._window_s]

    def _tooltip(self):
        values = [v for _, v in self._visible(time.time())]
        unit = f" {self._unit}" if self._unit else ""
        minutes = self._window_s / 60
        shown = f"{minutes:g} min" if minutes < 120 else f"{minutes / 60:g} h"
        if not values:
            return f"{self._name}: no reading in the last {shown}"
        return (f"{self._name}: {values[-1]:.4g}{unit}\nlast {shown}: from {min(values):.4g} to {max(values):.4g}{unit}")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        plot = QRect(2, 3, self.LINE_WIDTH, self.height() - 6)
        points = self._visible(time.time())
        if points:
            low, high = min(v for _, v in points), max(v for _, v in points)
            span = (high - low) or 1.0  # a flat series is drawn in the middle
            line = [QPointF(plot.left() + plot.width() * fraction,
                            plot.top() + plot.height() * (0.5 if high == low else 1 - (value - low) / span))
                    for fraction, value in decimate(points, max(plot.width(), 1))]
            painter.setPen(QPen(self._color, 1.4))
            if len(line) > 1:
                painter.drawPolyline(QPolygonF(line))
            painter.setBrush(self._color)
            painter.drawEllipse(line[-1], 2.0, 2.0)  # latest value
        else:
            painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashLine))
            painter.drawLine(plot.left(), plot.center().y(), plot.right(), plot.center().y())
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 6.0))
        painter.setFont(font)
        painter.setPen(self._color)  # the name has the colour of its line
        painter.drawText(QRect(plot.right() + 6, 0, self.NAME_WIDTH, self.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideLeft, self.NAME_WIDTH - 2))


class StatusSparklines(QWidget):
    """The row of sparklines shown in the status bar: the monitored parameters whose time trace is ticked in the
    Monitor tab (``refresh`` is called when it redraws its traces), in table order, at most the number set in the settings, over the duration set there. Hidden when
    switched off or when there is nothing to show."""

    def __init__(self, settings, series_provider):
        """``series_provider(window_s, maximum)`` gives [(name, unit, points, slot)] (the Monitor tab's)."""
        super().__init__()
        self.settings = settings
        self._series_provider = series_provider
        self._sparks = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._layout = layout
        self.setVisible(False)
        settings.changed.connect(self.refresh)  # the toggle, the number and the duration are set in the Settings

    def refresh(self):
        """Redraw from the Monitor tab and the settings (also after a change of the settings)."""
        settings = self.settings
        series = []
        if settings.show_sparklines:
            series = self._series_provider(settings.sparkline_minutes * 60, settings.sparkline_max)
        while len(self._sparks) > len(series):
            spark = self._sparks.pop()
            self._layout.removeWidget(spark)
            spark.deleteLater()
        while len(self._sparks) < len(series):
            spark = Sparkline()
            self._sparks.append(spark)
            self._layout.addWidget(spark)
        for spark, (name, unit, points, slot) in zip(self._sparks, series):
            spark.set_series(name, unit, points, settings.sparkline_minutes * 60, slot)
        self.setVisible(bool(series))
