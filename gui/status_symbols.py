from __future__ import annotations

from PyQt6.QtGui import QColor, QIcon
from shared_ui.colors import GREEN, RED, TEXT_MUTED
from shared_ui.icons import icon_pixmap

GRAY = TEXT_MUTED

_MARK_PX = 16

CHECK = "check"
CROSS = "cross"
CIRCLE = "circle"

_MARKS = {
    "success": (CHECK, GREEN),
    "completed": (CHECK, GREEN),
    "warning": (CIRCLE, GRAY),
    "skipped": (CIRCLE, GRAY),
    "error": (CROSS, RED),
}

_NO_MARK = ("", GRAY)


def symbol_for(status: str) -> tuple[str, QColor]:
    return _MARKS.get(status, _NO_MARK)


def status_icon(status: str) -> QIcon:
    mark, color = symbol_for(status)
    if not mark:
        return QIcon()
    return QIcon(icon_pixmap(mark, _MARK_PX, color))
