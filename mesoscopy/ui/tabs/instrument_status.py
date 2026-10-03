"""Per-instrument identity and health display for the "Connected instruments" list."""
import time
from datetime import datetime

from PyQt6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip,
)

from mesoscopy.core.gateway import BACKGROUND
from mesoscopy.instrument.status import get_identity

ROLE_IDN = Qt.ItemDataRole.UserRole + 1    # dict: vendor/model/serial/firmware (or None)
ROLE_OK = Qt.ItemDataRole.UserRole + 2     # True / False / None (not checked yet)
ROLE_TIME = Qt.ItemDataRole.UserRole + 3   # datetime of the last get_idn() check (or None)
ROLE_ERROR = Qt.ItemDataRole.UserRole + 4  # error message of the last failed check

COLOR_OK = QColor("#2e9e4f")
COLOR_FAIL = QColor("#d64545")
COLOR_UNKNOWN = QColor("#9a9a9a")


class InstrumentStatusDelegate(QStyledItemDelegate):
    """Paints "name / Model - Serial" with a health circle on the right, plus tooltips."""

    CIRCLE = 12
    PAD = 8

    def _circle_rect(self, rect):
        return QRect(rect.right() - self.PAD - self.CIRCLE, rect.center().y() - self.CIRCLE // 2,
                     self.CIRCLE, self.CIRCLE)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), option.fontMetrics.height() * 2 + 10)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        group = QPalette.ColorGroup.Active
        main_color = option.palette.color(group, QPalette.ColorRole.HighlightedText if selected
                                          else QPalette.ColorRole.Text)
        sub_color = QColor(main_color)
        sub_color.setAlpha(150)

        idn = index.data(ROLE_IDN)
        sub_text = f"{idn['model']} · {idn['serial']}" if idn else "checking..."

        circle = self._circle_rect(option.rect)
        text_width = circle.left() - option.rect.left() - 2 * self.PAD
        fm = option.fontMetrics
        line_h = fm.height()
        x = option.rect.left() + self.PAD
        y = option.rect.top() + 4

        painter.save()
        bold = QFont(option.font)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(main_color)
        painter.drawText(QRect(x, y, text_width, line_h), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                                          Qt.TextElideMode.ElideRight, text_width))
        painter.setFont(option.font)
        painter.setPen(sub_color)
        painter.drawText(QRect(x, y + line_h, text_width, line_h), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(sub_text, Qt.TextElideMode.ElideRight, text_width))

        ok = index.data(ROLE_OK)
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(COLOR_UNKNOWN if ok is None else COLOR_OK if ok else COLOR_FAIL)
        painter.drawEllipse(circle)
        painter.restore()

    @staticmethod
    def identity_tooltip(index):
        idn = index.data(ROLE_IDN)
        if not idn:
            return "Identity not available yet."
        return (f"Vendor: {idn['vendor']}\nModel: {idn['model']}\n"
                f"Serial: {idn['serial']}\nFirmware: {idn['firmware']}")

    @staticmethod
    def health_tooltip(index):
        when = index.data(ROLE_TIME)
        ok = index.data(ROLE_OK)
        if when is None:
            text = "get_idn() not checked yet."
            if ok is False:  # e.g. the first check never answered
                text = f"No response: {index.data(ROLE_ERROR)}"
            return text
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            return f"Last get_idn() check: {stamp} (responding)"
        return f"Last get_idn() check: {stamp}\nNo valid answer: {index.data(ROLE_ERROR)}"

    def helpEvent(self, event, view, option, index):
        if event.type() == QEvent.Type.ToolTip and index.isValid():
            over_circle = self._circle_rect(option.rect).contains(event.pos())
            text = self.health_tooltip(index) if over_circle else self.identity_tooltip(index)
            QToolTip.showText(event.globalPos(), text, view, option.rect)
            return True
        return super().helpEvent(event, view, option, index)


class InstrumentHealthMonitor(QObject):
    """
    Periodically calls get_idn() on every instrument of the station and keeps
    ``status[name] = {idn, ok, time, error}``. The calls go through the instrument gateway as background
    jobs: an instrument that is in use (a measurement, a ramp) is simply not checked this time.
    An instrument that does not answer within ``timeout_s`` is reported as failing.
    """

    changed = pyqtSignal()

    def __init__(self, parent, get_components, gateway, interval_ms=5000, timeout_s=10.0):
        super().__init__(parent)
        self._get_components = get_components
        self._gateway = gateway
        self._timeout_s = timeout_s
        self._inflight = {}  # name -> (start time, job)
        self.status = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(interval_ms)

    def stop(self):
        self._timer.stop()

    def forget(self, name):
        """Drop the status of ``name`` so it is re-checked from scratch (e.g. after a reload)."""
        self.status.pop(name, None)
        self._inflight.pop(name, None)

    def sync(self):
        """Match tracked names to the station and check newly appeared instruments right away."""
        components = self._get_components()
        for name in [n for n in self.status if n not in components]:
            del self.status[name]
            self._inflight.pop(name, None)
        new = [n for n in components if n not in self.status]
        for name in new:
            self.status[name] = {"idn": None, "ok": None, "time": None, "error": ""}
        self._check(new)
        self.changed.emit()

    def _tick(self):
        self._check(list(self._get_components()))

    def _check(self, names):
        components = self._get_components()
        for name in names:
            instrument = components.get(name)
            if instrument is None:
                continue
            if name in self._inflight:
                started, _ = self._inflight[name]
                if time.monotonic() - started > self._timeout_s and self.status[name]["ok"] is not False:
                    self.status[name]["ok"] = False
                    self.status[name]["error"] = f"no response for more than {self._timeout_s:g} s"
                    self.changed.emit()
                continue
            job = self._gateway.submit(get_identity, instrument, kind=BACKGROUND, instruments={name},
                                       label=f"Checking {name}")
            if job is None:  # the instrument is in use: checked at the next tick
                continue
            job.signals.result.connect(lambda identity, n=name, j=job: self._on_result(n, identity, "", j))
            job.signals.error.connect(
                lambda err, n=name, j=job: self._on_result(n, None, f"{type(err[1]).__name__}: {err[1]}", j)
            )
            self._inflight[name] = (time.monotonic(), job)

    def _on_result(self, name, identity, error, job):
        if self._inflight.get(name, (None, None))[1] is not job:
            return  # stale result of an instrument that was forgotten or reloaded meanwhile
        self._inflight.pop(name, None)
        entry = self.status.get(name)
        if entry is None:  # disconnected in the meantime
            return
        entry["time"] = datetime.now()
        entry["ok"] = identity is not None
        entry["error"] = error
        if identity is not None:
            entry["idn"] = identity
        self.changed.emit()
