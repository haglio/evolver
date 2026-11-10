from __future__ import annotations

from PyQt6.QtGui import QIcon
from shared_ui.icons import qt_icon


def restart_icon(color: str) -> QIcon:
    return qt_icon("restart", color=color)


def quit_icon(color: str) -> QIcon:
    return qt_icon("power", color=color)


def run_now_icon(color: str) -> QIcon:
    return qt_icon("play", color=color)


def pause_icon(color: str) -> QIcon:
    return qt_icon("pause", color=color)

