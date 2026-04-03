"""System tray icon with context menu."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

import qtawesome as qta

import config

_ICON_COLOR = "#333"


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
        self._is_running = False
        self._is_paused = False
        self._next_run_at: datetime | None = None
        self._update_tooltip()

        self._menu = QMenu()

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

        self.run_now_action = QAction(qta.icon("fa5s.play", color=_ICON_COLOR), "Run Now", self._menu)
        self._menu.addAction(self.run_now_action)

        self.pause_action = QAction(qta.icon("fa5s.pause", color=_ICON_COLOR), "Pause Scheduling", self._menu)
        self._menu.addAction(self.pause_action)

        self._menu.addSeparator()

        self.settings_action = QAction(qta.icon("fa5s.cog", color=_ICON_COLOR), "Settings...", self._menu)
        self._menu.addAction(self.settings_action)

        self.stats_action = QAction(qta.icon("fa5s.chart-bar", color=_ICON_COLOR), "Stats...", self._menu)
        self._menu.addAction(self.stats_action)

        self._menu.addSeparator()

        self.restart_action = QAction(qta.icon("fa5s.redo", color=_ICON_COLOR), "Restart", self._menu)
        self._menu.addAction(self.restart_action)

        self.quit_action = QAction(qta.icon("fa5s.power-off", color=_ICON_COLOR), "Quit", self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

        self._update_status_actions()

        # Double-click opens the window
        self.activated.connect(self._on_activated)

    def set_running(self, running: bool):
        self._is_running = running
        self.run_now_action.setEnabled(not running)
        self._update_tooltip()
        self._update_status_actions()

    def set_paused(self, paused: bool):
        self._is_paused = paused
        self.pause_action.setText("Resume Scheduling" if paused else "Pause Scheduling")
        self._update_tooltip()
        self._update_status_actions()

    def set_next_run_at(self, next_run_at: datetime | None):
        self._next_run_at = next_run_at
        self._update_tooltip()
        self._update_status_actions()

    def _update_tooltip(self):
        parts = ["Evolver"]
        if self._is_running:
            parts.append("Running...")
        elif self._is_paused:
            parts.append("Paused")
        elif self._next_run_at:
            parts.append(f"Next run: {self._next_run_at.strftime('%H:%M')}")
        self.setToolTip(" - ".join(parts))

    def _update_status_actions(self):
        if self._is_running:
            self._status_action.setText("Status: Running")
        elif self._is_paused:
            self._status_action.setText("Status: Paused")
        else:
            self._status_action.setText("Status: Scheduled")

        if self._next_run_at and not self._is_running and not self._is_paused:
            self._next_run_action.setText(f"Next run: {self._next_run_at.strftime('%H:%M')}")
            self._next_run_action.setVisible(True)
        else:
            self._next_run_action.setVisible(False)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_action.trigger()
