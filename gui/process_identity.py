"""What this process tells Windows it is, so a pinned button says Evolver.

A PyQt app launched through ``pythonw.exe`` is, as far as the shell is
concerned, pythonw: a pinned taskbar button belongs to Python, carries Python's
icon, and relaunches Python with no arguments. Two calls fix that and they
belong together -- one names the process, the other names the window it puts on
the taskbar -- and both are things the app *does* to the machine it is running
on, which is why they are here and not in a constructor.
"""

from __future__ import annotations

import ctypes
import sys

import config
from gui.taskbar import set_taskbar_properties

# The Windows identity contract. A pinned shortcut belongs to whatever this
# says, so it is the one string that must not drift.
APP_MODEL_ID = "Evolver.TrayApp"
DISPLAY_NAME = "Evolver"


def claim(hwnd: int) -> None:
    """Name this process to the shell, and *hwnd* to the taskbar."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)
    set_taskbar_properties(
        hwnd,
        APP_MODEL_ID,
        _relaunch_command(),
        DISPLAY_NAME,
        str(config.PROJECT_DIR / "icon.ico"),
    )


def _relaunch_command() -> str:
    """What the shell runs when a pinned Evolver button is clicked.

    Quoted here rather than at the call site: both halves are paths that
    routinely hold spaces, and a relaunch command the shell cannot parse pins
    a button that does nothing.
    """
    return f'"{sys.executable}" "{config.PROJECT_DIR / "tray_app.py"}" --show-window'
