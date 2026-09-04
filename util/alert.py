"""Evolver's way of saying what a stage could not go on without.

Everything Qt is imported inside the call, not at the top: the startup crash
reporter comes through here on an interpreter that has just failed to import
something, and PyQt6 is one of the things it could have failed on.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

ICON_FILE = Path(__file__).resolve().parent.parent / "icon.ico"


def show_error(title: str, message: str) -> None:
    """Put *message* on the screen under *title*, and block until it is read."""
    try:
        from shared_ui.alert import show_alert

        show_alert(title, message, icon=ICON_FILE)
    except Exception:
        log.exception("Could not open the alert dialog: %s", title)
        _fall_back_to_windows(title, message)


def _fall_back_to_windows(title: str, message: str) -> None:
    try:
        from app_support.win32 import show_error_popup

        show_error_popup(title, message)
    except Exception:
        log.exception("Could not open the Windows dialog either: %s", title)
