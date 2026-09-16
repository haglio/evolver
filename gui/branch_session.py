"""A branch's whole Evolver, opened beside the one the user runs every day.

``launch_preview_branch.vbs`` in a worktree starts that branch's app with
``EVOLVER_BRANCH_SESSION=1``: the same tray icon, the same window, every
command working, on the live library and the live app's own run history, queue
manifests and settings (``config.LIVE_DIR``).  The user judges a change by
using the app, so the preview has to *be* the app — a slice of it, or one
window of it filled from a report, is a thing he cannot trust and has said so.

Two jobs stay with the live app, because two of either would fight: the
ten-minute schedule, which is two pipelines over one library, and the presence
poll that parks the non-AI encode, which from two processes would freeze the
one encode twice over and thaw it once.  So a branch session runs nothing on a
timer; what it does, it does because somebody clicked it.  The pipeline lock
(:mod:`util.run_lock`) is what keeps a Run Now here from landing on top of a
scheduled run over there.
"""

from __future__ import annotations

import subprocess
import sys

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config

#: Why the two schedule controls are disabled in a preview, said where they are.
SCHEDULE_IS_THE_LIVE_APPS = "The Evolver you run keeps the schedule"


def is_one() -> bool:
    return config.BRANCH_SESSION


def branch() -> str:
    """The branch this worktree is on, for the window that has to say so."""
    try:
        done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=config.PROJECT_DIR, capture_output=True, text=True,
                              check=False, **hidden_subprocess_kwargs())
    except OSError:
        return config.PROJECT_DIR.name
    return done.stdout.strip() or config.PROJECT_DIR.name


def app_name() -> str:
    """What this instance calls itself, on a window title and a tray hover."""
    return f"Evolver — preview of {branch()}" if is_one() else "Evolver"


def model_id(live: str) -> str:
    """The Windows identity, so a preview's button never merges with the live one's."""
    return f"{live}.Preview.{config.PROJECT_DIR.name}" if is_one() else live


def instance_suffix() -> str:
    """What a preview adds to the single-instance names it claims.

    Without it the preview would find the live app's mutex taken and hand its
    launch over to it — which is the one thing a preview must not do.
    """
    return f".preview.{config.PROJECT_DIR.name}" if is_one() else ""


def relaunch_command() -> str:
    """What the shell runs when this instance's taskbar button is clicked."""
    if is_one():
        return f'wscript.exe "{config.PROJECT_DIR / "launch_preview_branch.vbs"}"'
    return f'"{sys.executable}" "{config.PROJECT_DIR / "tray_app.py"}" --show-window'
