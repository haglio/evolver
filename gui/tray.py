from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon
from shared_ui.chrome import menu_rules
from shared_ui.preview import Preview
from shared_ui.preview_icon import app_icon
from shared_ui.toggle_switch import ToggleSwitch

import config
from gui.commands import (
    NONAI,
    OPEN,
    PAUSE,
    QUEUE,
    QUIT,
    RESTART,
    REVIEW_TRASH,
    RUN_NOW,
    SETTINGS,
    STATS,
    pause_or_resume,
    set_label,
)
from gui.schedule_state import ScheduleStatus
from gui.switches import MenuWithSwitches


class EvolverTray(QSystemTrayIcon):

    def __init__(self, name: str = "Evolver", parent=None, *, shown_as: Preview | None = None):
        super().__init__(app_icon(config.PROJECT_DIR / "icon.ico", shown_as), parent)
        self._name = name

        self._menu = MenuWithSwitches()
        # Qt cascades a style sheet down from a parent widget, and a tray menu has none.
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

        self.nonai_action = NONAI.action(self._menu)
        self.nonai_switch = ToggleSwitch()
        self.nonai_action.triggered.connect(self.nonai_switch.click)
        self._menu.addAction(self.nonai_action)
        self._menu.put_switch_on(self.nonai_action, self.nonai_switch)

        self._menu.addSeparator()

        self.settings_action = SETTINGS.action(self._menu)
        self._menu.addAction(self.settings_action)

        self.stats_action = STATS.action(self._menu)
        self._menu.addAction(self.stats_action)

        self._menu.addSeparator()

        self.queue_action = QUEUE.action(self._menu)
        self._menu.addAction(self.queue_action)

        self.review_trash_action = REVIEW_TRASH.action(self._menu)
        self._menu.addAction(self.review_trash_action)

        self._menu.addSeparator()

        self.restart_action = RESTART.action(self._menu)
        self._menu.addAction(self.restart_action)

        self.quit_action = QUIT.action(self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

        self.show_schedule(ScheduleStatus())

        self.activated.connect(self._on_activated)

    def commands(self):
        return {
            "open": self.open_action.triggered,
            "run_now": self.run_now_action.triggered,
            "pause": self.pause_action.triggered,
            "nonai": self.nonai_switch.clicked,
            "settings": self.settings_action.triggered,
            "stats": self.stats_action.triggered,
            "queue": self.queue_action.triggered,
            "review_trash": self.review_trash_action.triggered,
            "restart": self.restart_action.triggered,
            "quit": self.quit_action.triggered,
        }

    def set_nonai_enabled(self, enabled: bool):
        self.nonai_switch.setChecked(enabled)

    def show_schedule(self, status: ScheduleStatus):
        self.run_now_action.setEnabled(not status.is_running)
        set_label(self.pause_action, pause_or_resume(status.is_paused))
        self.setToolTip(" - ".join(
            part for part in (self._name, status.activity()) if part))
        self._status_action.setText(f"Status: {status.headline()}")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_action.trigger()
