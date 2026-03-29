"""System tray icon with context menu."""

from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


STAGE_NAMES = ["sort", "purge", "scripts", "bookmarks", "metadata", "upscale", "dupes", "verify"]


def _make_icon() -> QIcon:
    """Draw a simple 'E' icon for the tray."""
    px = QPixmap(32, 32)
    px.fill(QColor(0x30, 0x80, 0xE0))
    painter = QPainter(px)
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI", 18, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(px.rect(), 0x0084, "E")  # AlignCenter
    painter.end()
    return QIcon(px)


class EvolverTray(QSystemTrayIcon):
    """System tray icon with Open / Run Now / Pause / Settings / Quit menu."""

    def __init__(self, parent=None):
        super().__init__(_make_icon(), parent)
        self.setToolTip("Evolver")

        self._menu = QMenu()

        self.open_action = QAction("Open", self._menu)
        font = self.open_action.font()
        font.setBold(True)
        self.open_action.setFont(font)
        self._menu.addAction(self.open_action)

        self.run_now_action = QAction("Run Now", self._menu)
        self._menu.addAction(self.run_now_action)

        self.pause_action = QAction("Pause Scheduling", self._menu)
        self._menu.addAction(self.pause_action)

        self._menu.addSeparator()

        self.settings_action = QAction("Settings...", self._menu)
        self._menu.addAction(self.settings_action)

        self._menu.addSeparator()

        self.quit_action = QAction("Quit", self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

        # Double-click opens the window
        self.activated.connect(self._on_activated)

    def set_running(self, running: bool):
        self.run_now_action.setEnabled(not running)
        if running:
            self.setToolTip("Evolver - Running...")
        else:
            self.setToolTip("Evolver")

    def set_paused(self, paused: bool):
        self.pause_action.setText("Resume Scheduling" if paused else "Pause Scheduling")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_action.trigger()
