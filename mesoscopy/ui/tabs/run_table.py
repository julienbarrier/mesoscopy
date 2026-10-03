"""Rows of a table of runs: the tag as a coloured dot before the name, the notes in a tooltip."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidgetItem

from mesoscopy.core.run_tags import TAGS

# the stored value is the colour's name; these are the colours drawn
TAG_COLORS = {"red": "#e0392b", "orange": "#f28c1e", "yellow": "#f2c80f", "green": "#2e9e4f", "blue": "#2d7dd2",
              "purple": "#8e5bc8"}
assert set(TAG_COLORS) == set(TAGS)
ROLE_RUN = Qt.ItemDataRole.UserRole + 1  # the run as listed (dict), kept on the name item


DOT_SIZE = 14  # the dot of the run table, and of the run menu


def dot_pixmap(color, size=DOT_SIZE, selected=False):
    """A filled round dot; ``selected`` gives it a thick dark outline."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QPen(QColor("#333333"), 2) if selected else QPen(QColor(color).darker(130), 1))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return pixmap


def fill_run_row(table, row, run):
    """Fill row ``row`` of a table whose columns are ``RUN_COLUMNS`` from a run dict (see ``list_runs``). The tag is a
    dot in the name cell, before the name; the notes are the tooltip of that cell."""
    values = (run["run_id"], run["name"], run["started"], "completed" if run["completed"] else "not completed",
              run["n_results"])
    for column, value in enumerate(values):
        table.setItem(row, column, QTableWidgetItem(str(value)))
    table.item(row, 0).setData(Qt.ItemDataRole.UserRole, run["run_id"])
    name_item = table.item(row, 1)
    name_item.setData(ROLE_RUN, run)
    tag = run.get("tag", "")
    name_item.setIcon(QIcon(dot_pixmap(TAG_COLORS[tag])) if tag in TAG_COLORS else QIcon())
    tips = [f"Measurement: {run['name']}"] + ([f"Tag: {tag}"] if tag in TAG_COLORS else []) + \
           ([f"Notes:\n{run['notes']}"] if run.get("notes") else [])
    name_item.setToolTip("\n\n".join(tips))  # the full name and the full note, whatever the cell shows
    table.resizeRowToContents(row)  # a run with notes has a second line


def note_preview(notes):
    """The first line of the notes, with '...' when there is more."""
    lines = [line for line in (notes or "").strip().splitlines()]
    if not lines:
        return ""
    return lines[0].strip() + (" \u2026" if any(line.strip() for line in lines[1:]) else "")


class RunNameDelegate(QStyledItemDelegate):
    """The name cell of a run: the tag dot and the name, and, when the run has notes, a one-line preview of them under
    the name in a smaller, fainter font. The row is taller for such a run."""

    PAD = 4

    def _note(self, index):
        return note_preview((index.data(ROLE_RUN) or {}).get("notes"))

    def _small(self, font):
        small = QFont(font)
        small.setPointSizeF(max(font.pointSizeF() - 1.5, 7.0))
        return small

    def sizeHint(self, option, index):
        height = option.fontMetrics.height() + 2 * self.PAD
        if self._note(index):
            height += QFontMetrics(self._small(option.font)).height()
        return QSize(option.rect.width(), height)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, icon = opt.text, QIcon(opt.icon)  # a copy: the option's own icon is cleared just below
        opt.text, opt.icon = "", QIcon()
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)  # background, selection
        color = opt.palette.highlightedText().color() if opt.state & QStyle.StateFlag.State_Selected \
            else opt.palette.text().color()
        fm = opt.fontMetrics
        rect = opt.rect.adjusted(self.PAD + 2, self.PAD, -self.PAD, -self.PAD)
        x = rect.left()
        painter.save()
        if not icon.isNull():
            painter.drawPixmap(x, rect.top() + (fm.height() - DOT_SIZE) // 2, icon.pixmap(DOT_SIZE, DOT_SIZE))
            x += DOT_SIZE + 6
        painter.setPen(color)
        painter.setFont(opt.font)
        painter.drawText(x, rect.top(), rect.right() - x, fm.height(), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(text, Qt.TextElideMode.ElideRight, rect.right() - x))
        note = self._note(index)
        if note:
            small = self._small(opt.font)
            small_fm = QFontMetrics(small)
            faded = QColor(color)
            faded.setAlpha(160)
            painter.setPen(faded)
            painter.setFont(small)
            painter.drawText(x, rect.top() + fm.height(), rect.right() - x, small_fm.height(),
                             Qt.AlignmentFlag.AlignVCenter,
                             small_fm.elidedText(note, Qt.TextElideMode.ElideRight, rect.right() - x))
        painter.restore()


def setup_run_table(table):
    """Make a table of runs (columns ``RUN_COLUMNS``) show the tag dot and the note preview in the name cell."""
    table.setItemDelegateForColumn(1, RunNameDelegate(table))
