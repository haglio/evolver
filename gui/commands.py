from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtGui import QAction, QIcon
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import glyph_icon

from gui.icons import pause_icon, quit_icon, restart_icon, review_weird_icon, run_now_icon


@dataclass(frozen=True)
class Command:
    label: str
    draw: Callable[[str], QIcon]

    def action(self, parent) -> QAction:
        action = QAction(self.draw(TEXT_SECONDARY.name()), "", parent)
        set_label(action, self.label)
        return action


def set_label(action: QAction, label: str) -> None:
    action.setText(label)
    action.setIconText(label)
    action.setToolTip(label)


def _mark(name: str) -> Callable[[str], QIcon]:
    return lambda color: glyph_icon(name, color=color)


OPEN = Command("Open", _mark("external_link"))
RUN_NOW = Command("Run Now", run_now_icon)
PAUSE = Command("Pause Scheduling", pause_icon)
NONAI = Command("Upscale Non-AI When Idle", _mark("moon"))
SETTINGS = Command("Settings...", _mark("settings"))
STATS = Command("Stats...", _mark("chart"))
QUEUE = Command("Upscale Queue...", _mark("enlarge"))
BACKFILL = Command("Backfill Metadata...", _mark("tag"))
REVIEW_WEIRD = Command("Review Weird...", review_weird_icon)
RESTART = Command("Restart", restart_icon)
QUIT = Command("Quit", quit_icon)


def pause_or_resume(is_paused: bool) -> str:
    return "Resume Scheduling" if is_paused else PAUSE.label
