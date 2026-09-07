"""System tray icon with context menu."""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from shared_ui.chrome import menu_rules
from shared_ui.colors import TEXT_SECONDARY

import config
from gui.icons import quit_icon, restart_icon, run_now_icon
from gui.schedule_state import ScheduleStatus

# The marks sit on the family's dark menu now, so they are its light text.
_ICON_COLOR = TEXT_SECONDARY.name()


def _make_icon() -> QIcon:
    """Load the E icon from the project .ico file."""
    icon_path = config.PROJECT_DIR / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


class EvolverTray(QSystemTrayIcon):
    """System tray icon with Open / Run Now / Pause / Settings / Quit menu."""

    def __init__(self, parent=None):
        super().__init__(_make_icon(), parent)

        self._menu = QMenu()
        # A tray menu has no window to take the family's rules from; without
        # them it rendered native, beside the broker's dark one.
        self._menu.setStyleSheet(menu_rules())

        self._status_action = QAction("", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)

        self._next_run_action = QAction("", self._menu)
        self._next_run_action.setEnabled(False)
        self._menu.addAction(self._next_run_action)

        self._menu.addSeparator()

        self.open_action = QAction(qta.icon("fa5s.external-link-alt", color=_ICON_COLOR), "Open", self._menu)
        font = self.open_action.font()
        font.setBold(True)
        self.open_action.setFont(font)
        self._menu.addAction(self.open_action)

        self.run_now_action = QAction(run_now_icon(_ICON_COLOR), "Run Now", self._menu)
        self._menu.addAction(self.run_now_action)

        self.pause_action = QAction(qta.icon("fa5s.pause", color=_ICON_COLOR), "Pause Scheduling", self._menu)
        self._menu.addAction(self.pause_action)

        # A one-time opt-in, off by default because a non-AI encode owns the
        # GPU for hours. Once on, Evolver runs it only while the user is idle
        # and suspends it the moment they return — no manual flipping.
        self.nonai_action = QAction(qta.icon("fa5s.film", color=_ICON_COLOR), "Upscale Non-AI When Idle", self._menu)
        self.nonai_action.setCheckable(True)
        self._menu.addAction(self.nonai_action)

        self._menu.addSeparator()

        self.settings_action = QAction(qta.icon("fa5s.cog", color=_ICON_COLOR), "Settings...", self._menu)
        self._menu.addAction(self.settings_action)

        self.stats_action = QAction(qta.icon("fa5s.chart-bar", color=_ICON_COLOR), "Stats...", self._menu)
        self._menu.addAction(self.stats_action)

        self.backfill_action = QAction(qta.icon("fa5s.microphone", color=_ICON_COLOR), "Backfill Metadata...", self._menu)
        self._menu.addAction(self.backfill_action)

        self._menu.addSeparator()

        self.restart_action = QAction(restart_icon(_ICON_COLOR), "Restart", self._menu)
        self._menu.addAction(self.restart_action)

        self.quit_action = QAction(quit_icon(_ICON_COLOR), "Quit", self._menu)
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
            "nonai": self.nonai_action.toggled,
            "settings": self.settings_action.triggered,
            "stats": self.stats_action.triggered,
            "backfill": self.backfill_action.triggered,
            "restart": self.restart_action.triggered,
            "quit": self.quit_action.triggered,
        }

    def set_nonai_enabled(self, enabled: bool):
        """Show the saved state of the non-AI opt-in, without re-announcing it."""
        self.nonai_action.setChecked(enabled)

    def show_schedule(self, status: ScheduleStatus):
        """Put the schedule on all five of the tray's surfaces at once.

        Every one of them changes together on every change, so they are set
        together: the two that used to be updated in separate passes are how
        the tooltip and the menu could disagree about the same moment.
        """
        self.run_now_action.setEnabled(not status.is_running)
        self.pause_action.setText(
            "Resume Scheduling" if status.is_paused else "Pause Scheduling")
        self.setToolTip(" - ".join(
            part for part in ("Evolver", status.activity()) if part))
        self._status_action.setText(f"Status: {status.headline()}")
        self._next_run_action.setText(status.next_run_text())
        self._next_run_action.setVisible(bool(status.next_run_text()))

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_action.trigger()
