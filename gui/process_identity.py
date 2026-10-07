"""What this process tells Windows it is, so a pinned button says Evolver.

A PyQt app launched through ``pythonw.exe`` is, as far as the shell is
concerned, pythonw: a pinned taskbar button belongs to Python, carries Python's
icon, and relaunches Python with no arguments. Two calls fix that and they
belong together -- one names the process, the other names the window it puts on
the taskbar -- and both are things the app *does* to the machine it is running
on, which is why they are here and not in a constructor.
"""

from __future__ import annotations

import logging

from app_support.win32 import TaskbarApp, dress_window, set_app_user_model_id
from shared_ui.preview_icon import icon_file

import config
from gui import branch_session
from util.preview import shown_as

log = logging.getLogger(__name__)

# The Windows identity contract. A pinned shortcut belongs to whatever this
# says, so it is the one string that must not drift.
APP_MODEL_ID = "Evolver.TrayApp"


def claim(hwnd: int) -> None:
    """Name this process to the shell, and *hwnd* to the taskbar.

    A refusal is logged, not raised: a button wearing Python's icon is still a
    button, and an icon is never worth failing to start over.
    """
    identity = branch_session.model_id(APP_MODEL_ID)
    try:
        set_app_user_model_id(identity)
    except OSError:
        log.warning("Could not claim the taskbar identity", exc_info=True)
    try:
        dress_window(hwnd, identity, TaskbarApp(
            name=branch_session.app_name(),
            icon=icon_file(config.PROJECT_DIR / "icon.ico", shown_as(), config.LOCAL_STATE_DIR),
            relaunch=branch_session.relaunch_command(),
        ))
    except OSError:
        log.warning("Could not tell the taskbar what this window is", exc_info=True)
