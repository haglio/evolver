"""One colored symbol per status, shared by every view that shows a status.

A run reports "success" or "error"; a stage reports "completed", "skipped" or
"error". Those are the same verdicts under two spellings, so they draw the same
marks — a run's green check is its stages' green check — and the color goes on
the symbol alone. A failed run is a red ✘ beside a plainly-colored timestamp,
not a whole line in red, which used to make a run's own verdict indistinguishable
from a stage of it having gone wrong.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

GREEN = QColor(0x30, 0xA0, 0x30)
RED = QColor(0xFF, 0x3C, 0x3C)
GRAY = QColor(0x80, 0x80, 0x80)

CHECK = "✔"
CROSS = "✘"
CIRCLE = "○"  # nothing ran here — an outline, not a filled dot

_MARKS = {
    "success": (CHECK, GREEN),
    "completed": (CHECK, GREEN),
    "skipped": (CIRCLE, GRAY),
    "error": (CROSS, RED),
}

_NO_MARK = ("", GRAY)


def mark_for(status: str) -> tuple[str, QColor]:
    """The glyph and color that stand for *status*.

    A status this build does not draw — run records on disk go back months —
    gets an empty glyph, so an old record renders blank instead of raising in
    the middle of painting the history.
    """
    return _MARKS.get(status, _NO_MARK)


def mark_icon(status: str, size: int = 16) -> QIcon:
    """*status*'s mark as an icon, for a view that cannot color part of a row.

    A list item's text takes one color for the whole string, so the run history
    could only redden the ✘ by reddening the timestamp beside it. Carrying the
    mark as the item's icon puts the color back on the symbol, and drawing that
    icon from the same glyph keeps it the same symbol the stage table shows.
    """
    glyph, color = mark_for(status)
    if not glyph:
        return QIcon()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(color)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)
