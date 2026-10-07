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
from datetime import datetime, timedelta

from app_support.subprocess_utils import hidden_subprocess_kwargs
from shared_ui.preview import taskbar_identity, window_title

import config
from util.preview import shown_as

#: How long a preview keeps the work if nobody quits it.
HAND_BACK_AFTER_MINUTES = 60


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


_WHAT_ONLY_A_PREVIEW_RUNS_WITH = (config.BRANCH_SESSION_FLAG, "PYTHONPATH")


def start_the_usual_evolver() -> None:
    """Start the Evolver the user runs, which takes the work back from this one.

    Hidden, the way the broker starts it: it comes back to the tray, not to
    the screen.
    """
    environment = {key: value for key, value in os.environ.items()
                   if key not in _WHAT_ONLY_A_PREVIEW_RUNS_WITH}
    subprocess.Popen(["wscript.exe", str(config.LIVE_DIR / "launch_evolver.vbs")],
                     cwd=str(config.LIVE_DIR), env=environment,
                     **hidden_subprocess_kwargs())
