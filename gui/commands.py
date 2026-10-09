from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import qtawesome as qta
from PyQt6.QtGui import QAction, QIcon
from shared_ui.colors import TEXT_SECONDARY

from gui.icons import pause_icon, quit_icon, restart_icon, review_weird_icon, run_now_icon


@dataclass(frozen=True)
class Command:
    label: str
    draw: Callable[[str], QIcon]

    def action(self, parent) -> QAction:
        return QAction(self.draw(TEXT_SECONDARY.name()), self.label, parent)


def _font_awesome(name: str) -> Callable[[str], QIcon]:
    return lambda color: qta.icon(name, color=color)


OPEN = Command("Open", _font_awesome("fa5s.external-link-alt"))
RUN_NOW = Command("Run Now", run_now_icon)
PAUSE = Command("Pause Scheduling", pause_icon)
NONAI = Command("Upscale Non-AI When Idle", _font_awesome("fa5s.film"))
SETTINGS = Command("Settings...", _font_awesome("fa5s.cog"))
STATS = Command("Stats...", _font_awesome("fa5s.chart-bar"))
QUEUE = Command("Upscale Queue...", _font_awesome("fa5s.list-ol"))
BACKFILL = Command("Backfill Metadata...", _font_awesome("fa5s.microphone"))
REVIEW_WEIRD = Command("Review Weird...", review_weird_icon)
RESTART = Command("Restart", restart_icon)
QUIT = Command("Quit", quit_icon)


def pause_or_resume(is_paused: bool) -> str:
    return "Resume Scheduling" if is_paused else PAUSE.label
