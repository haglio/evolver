from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timedelta

from app_support.subprocess_utils import hidden_subprocess_kwargs
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from shared_ui.preview import taskbar_identity, window_title

import config
from gui import peer_watch, single_instance
from util import crash_log
from util.preview import shown_as

HAND_BACK_AFTER_MINUTES = 60
HAND_BACK_RETRY_MS = 60_000


def is_one() -> bool:
    return config.BRANCH_SESSION


def app_name() -> str:
    return window_title("Evolver", shown_as())


def until(now: datetime) -> str:
    handed_back = now + timedelta(minutes=HAND_BACK_AFTER_MINUTES)
    return handed_back.strftime("%I:%M %p").lstrip("0")


def model_id(live: str) -> str:
    """The Windows identity, so a preview's button never merges with the live one's."""
    return taskbar_identity(live, shown_as())


def relaunch_command() -> str:
    if is_one():
        return f'wscript.exe "{config.PROJECT_DIR / "launch_preview_branch.vbs"}"'
    return f'"{sys.executable}" "{config.PROJECT_DIR / "tray_app.py"}" --show-window'


class BranchSession(QObject):
    leaving = pyqtSignal()

    def __init__(self, instance: single_instance.InstanceGateway,
                 a_run_is_going: Callable[[], bool], parent=None):
        super().__init__(parent)
        self.is_preview = is_one()
        self.name = app_name()
        self._instance = instance
        self._a_run_is_going = a_run_is_going
        self._hand_back = QTimer(self)
        self._hand_back.setSingleShot(True)
        self._hand_back.setInterval(HAND_BACK_AFTER_MINUTES * 60_000)
        self._hand_back.timeout.connect(self._hand_back_when_free)

    def take_the_work(self) -> None:
        if self.is_preview:
            self._hand_back.start()

    def title(self, now: datetime) -> str:
        return f"{self.name}, until {until(now)}" if self.is_preview else self.name

    def steps_aside_for(self, launch: bytes) -> bool:
        if launch == single_instance.PREVIEW:
            return True
        return self.is_preview and launch == single_instance.USUAL

    def step_aside(self) -> None:
        crash_log.write_info("Stepping aside:", "another Evolver is taking the work over\n")
        self.leaving.emit()

    def quit(self) -> None:
        if self.is_preview:
            self._hand_back_now()
            return
        peer_watch.stand_evolver_down()
        self.leaving.emit()

    def quit_question(self) -> str:
        return ("Quit this preview? Your usual Evolver takes the work back."
                if self.is_preview else "Are you sure?")

    def restart_launcher(self, *, showing: bool) -> str:
        if self.is_preview:
            return "launch_preview_branch.vbs"
        return "launch_evolver_showing_its_window.vbs" if showing else "launch_evolver.vbs"

    def _hand_back_when_free(self) -> None:
        if self._a_run_is_going():
            self._hand_back.start(HAND_BACK_RETRY_MS)
            return
        self._hand_back_now()

    def _hand_back_now(self) -> None:
        self._instance.let_go()
        start_the_usual_evolver()
        self.leaving.emit()


_WHAT_ONLY_A_PREVIEW_RUNS_WITH = (config.BRANCH_SESSION_FLAG, "PYTHONPATH")


def start_the_usual_evolver() -> None:
    environment = {key: value for key, value in os.environ.items()
                   if key not in _WHAT_ONLY_A_PREVIEW_RUNS_WITH}
    subprocess.Popen(["wscript.exe", str(config.LIVE_DIR / "launch_evolver_if_not_running.vbs")],
                     cwd=str(config.LIVE_DIR), env=environment,
                     **hidden_subprocess_kwargs())
