"""A branch's whole Evolver, run in place of the one the user runs every day.

``launch_preview_branch.vbs`` in a worktree starts that branch's app with
``EVOLVER_BRANCH_SESSION=1``: the same tray icon, the same window, every
command working, on the live library and the usual Evolver's own run history,
queue lists and settings (``config.LIVE_DIR``).  The user judges a change
by using the app, so the preview has to *be* the app — a slice of it, or one
window of it filled from a report, is a thing he cannot trust and has said so.

Two Evolvers cannot both do the work: two schedules are two pipelines over one
library, and two presence polls freeze the one encode twice over and thaw it
once.  So a preview takes the work over — its launch has the usual Evolver
step aside (``gui/single_instance.py``) — and runs the schedule until it hands
the work back, which it does when it is quit and, if nobody quits it, after
:data:`HAND_BACK_AFTER_MINUTES`.  Handing back is letting go of the claim,
starting the usual Evolver and quitting.  The usual Evolver launched while a
preview runs takes the work back the same way a preview took it.  A preview
that dies instead leaves the claim free, and the broker's watch starts the
usual one.
"""

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

#: How long a preview keeps the work if nobody quits it.
HAND_BACK_AFTER_MINUTES = 60
#: How long a preview whose time is up waits for the run in flight to end.
HAND_BACK_RETRY_MS = 60_000


def is_one() -> bool:
    return config.BRANCH_SESSION


def app_name() -> str:
    """What this instance calls itself, on a window title and a tray hover."""
    return window_title("Evolver", shown_as())


def until(now: datetime) -> str:
    """When a preview started at *now* hands the work back, as a clock reads it."""
    handed_back = now + timedelta(minutes=HAND_BACK_AFTER_MINUTES)
    return handed_back.strftime("%I:%M %p").lstrip("0")


def model_id(live: str) -> str:
    """The Windows identity, so a preview's button never merges with the live one's."""
    return taskbar_identity(live, shown_as())


def relaunch_command() -> str:
    """What the shell runs when this instance's taskbar button is clicked."""
    if is_one():
        return f'wscript.exe "{config.PROJECT_DIR / "launch_preview_branch.vbs"}"'
    return f'"{sys.executable}" "{config.PROJECT_DIR / "tray_app.py"}" --show-window'


class BranchSession(QObject):
    """This Evolver's turn at the work: how it answers another launch, and how it ends.

    A preview's ends by handing the work back -- after its hour, or when it is
    quit -- and the usual Evolver's when he quits it, standing it down so the
    broker leaves it down.
    """

    #: This Evolver is done with the work: handed back, or taken over.
    leaving = pyqtSignal()

    def __init__(self, instance: single_instance.InstanceGateway,
                 a_run_is_going: Callable[[], bool], parent=None):
        super().__init__(parent)
        # Read once: which Evolver this process is was settled by the launcher
        # that started it, and every answer here has to agree.
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
        """Whether a launch that found this Evolver running takes the work from it.

        A preview always does, and a preview makes way for the Evolver the
        user runs. A launcher that says nothing predates the answers and
        leaves on the connection, so for that one the window opens.
        """
        if launch == single_instance.PREVIEW:
            return True
        return self.is_preview and launch == single_instance.USUAL

    def step_aside(self) -> None:
        crash_log.write_info("Stepping aside:", "another Evolver is taking the work over\n")
        self.leaving.emit()

    def quit(self) -> None:
        """The quit he asked for: a preview hands the work back, the usual
        Evolver leaves the mark that keeps the broker from starting it again."""
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
        """The claim goes first, so the Evolver started next can take it at once."""
        self._instance.let_go()
        start_the_usual_evolver()
        self.leaving.emit()


_WHAT_ONLY_A_PREVIEW_RUNS_WITH = (config.BRANCH_SESSION_FLAG, "PYTHONPATH")


def start_the_usual_evolver() -> None:
    """Start the Evolver the user runs, which takes the work back from this one.

    Hidden, the way the broker starts it: it comes back to the tray, not to
    the screen.
    """
    environment = {key: value for key, value in os.environ.items()
                   if key not in _WHAT_ONLY_A_PREVIEW_RUNS_WITH}
    subprocess.Popen(["wscript.exe", str(config.LIVE_DIR / "launch_evolver_if_not_running.vbs")],
                     cwd=str(config.LIVE_DIR), env=environment,
                     **hidden_subprocess_kwargs())
