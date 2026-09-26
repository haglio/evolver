"""Evolver's way of saying what a stage could not go on without.

Everything Qt is imported inside the call, not at the top: the startup crash
reporter comes through here on an interpreter that has just failed to import
something, and PyQt6 is one of the things it could have failed on.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger(__name__)

ICON_FILE = Path(__file__).resolve().parent.parent / "icon.ico"


def show_error(title: str, message: str, links: Sequence[tuple[str, Path]] = (), *,
               dismissible: bool = False) -> bool:
    """Put *message* on the screen under *title*, block until it is read, and say whether it was dismissed."""
    try:
        from shared_ui.alert import Link, show_alert  # noqa: PLC0415  (see the module docstring)

        return show_alert(title, message, icon=ICON_FILE,
                          links=[Link(text, target) for text, target in links],
                          dismissible=dismissible)
    except Exception:
        log.exception("Could not open the alert dialog: %s", title)
        targets = "\n".join(str(target) for _text, target in links)
        _fall_back_to_windows(title, f"{message}\n\n{targets}" if targets else message)
        return False


def _fall_back_to_windows(title: str, message: str) -> None:
    try:
        from app_support.win32 import show_error_popup  # noqa: PLC0415  (see the module docstring)

        show_error_popup(title, message)
    except Exception:
        log.exception("Could not open the Windows dialog either: %s", title)
