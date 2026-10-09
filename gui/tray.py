"""System tray icon with context menu."""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from shared_ui.chrome import menu_rules
from shared_ui.preview import Preview
from shared_ui.preview_icon import app_icon

import config
from gui.commands import (
    BACKFILL,
    NONAI,
    OPEN,
    PAUSE,
    QUEUE,
    QUIT,
    RESTART,
    REVIEW_WEIRD,
    RUN_NOW,
    SETTINGS,
    STATS,
    pause_or_resume,
)
from gui.schedule_state import ScheduleStatus


class EvolverTray(QSystemTrayIcon):

    def __init__(self, name: str = "Evolver", parent=None, *, shown_as: Preview | None = None):
        super().__init__(app_icon(config.PROJECT_DIR / "icon.ico", shown_as), parent)
        self._name = name

        self._menu = QMenu()
        # A tray menu has no window to take the family's rules from; without
        # them it rendered native, beside the broker's dark one.
        self._menu.setStyleSheet(menu_rules())

        self._status_action = QAction("", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)

        self._menu.addSeparator()

        self.open_action = OPEN.action(self._menu)
        font = self.open_action.font()
        font.setBold(True)
        self.open_action.setFont(font)
        self._menu.addAction(self.open_action)

        self.run_now_action = RUN_NOW.action(self._menu)
        self._menu.addAction(self.run_now_action)

        self.pause_action = PAUSE.action(self._menu)
        self._menu.addAction(self.pause_action)

        # A one-time opt-in, off by default because a non-AI encode owns the
        # GPU for hours. Once on, Evolver runs it only while the user is idle
        # and suspends it the moment they return — no manual flipping.
        self.nonai_action = NONAI.action(self._menu)
        self.nonai_action.setCheckable(True)
        self._menu.addAction(self.nonai_action)

        self._menu.addSeparator()

        self.settings_action = SETTINGS.action(self._menu)
        self._menu.addAction(self.settings_action)

        self.stats_action = STATS.action(self._menu)
        self._menu.addAction(self.stats_action)

        self._menu.addSeparator()

        self.queue_action = QUEUE.action(self._menu)
        self._menu.addAction(self.queue_action)

        self.backfill_action = BACKFILL.action(self._menu)
        self._menu.addAction(self.backfill_action)

        self.review_weird_action = REVIEW_WEIRD.action(self._menu)
        self._menu.addAction(self.review_weird_action)

        self._menu.addSeparator()

        self.restart_action = RESTART.action(self._menu)
        self._menu.addAction(self.restart_action)

        self.quit_action = QUIT.action(self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

        # An idle schedule until the scheduler says otherwise, which it does as
        # soon as it starts -- but the icon is in the tray before that.
        self.show_schedule(ScheduleStatus())

        # Double-click opens the window
        self.activated.connect(self._on_activated)

    def commands(self):
        """Each menu command's signal, by the name the app knows it as.

        The app connected ten widget attributes of this class by hand, which
        made every tray control something two files had to agree about with
        nothing checking they did. Now the menu says what it offers and the app
        says what each one does.
        """
        return {
            "open": self.open_action.triggered,
            "run_now": self.run_now_action.triggered,
            "pause": self.pause_action.triggered,
            "nonai": self.nonai_action.triggered,
            "settings": self.settings_action.triggered,
            "stats": self.stats_action.triggered,
            "queue": self.queue_action.triggered,
            "backfill": self.backfill_action.triggered,
            "review_weird": self.review_weird_action.triggered,
            "restart": self.restart_action.triggered,
            "quit": self.quit_action.triggered,
        }

    def set_nonai_enabled(self, enabled: bool):
        """Show the saved state of the non-AI opt-in, without re-announcing it."""
        self.nonai_action.setChecked(enabled)

    def show_schedule(self, status: ScheduleStatus):
        """Put the schedule on every one of the tray's surfaces at once.

        Every one of them changes together on every change, so they are set
        together: updating any of them in a pass of its own is what lets the
        tooltip and the menu disagree about the same moment.
        """
        self.run_now_action.setEnabled(not status.is_running)
        self.pause_action.setText(pause_or_resume(status.is_paused))
        self.setToolTip(" - ".join(
            part for part in (self._name, status.activity()) if part))
        self._status_action.setText(f"Status: {status.headline()}")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_action.trigger()
