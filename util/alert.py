# Qt is imported inside the call: the startup crash reporter comes through here when PySide6 may be what failed to import.

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from app_support.claude_sessions import new_session_link

log = logging.getLogger(__name__)

CHECKOUT = Path(__file__).resolve().parent.parent
ICON_FILE = CHECKOUT / "icon.ico"


def show_error(title: str, message: str, links: Sequence[tuple[str, Path]] = (), *,
               dismissible: bool = False) -> bool:
    try:
        from shared_ui.alert import Link, show_alert  # noqa: PLC0415  (see the module docstring)
        from shared_ui.preview_icon import app_icon  # noqa: PLC0415  (see the module docstring)

        from util.preview import shown_as  # noqa: PLC0415  (see the module docstring)

        shown = shown_as()
        return show_alert(title, message, icon=ICON_FILE if shown is None else app_icon(ICON_FILE, shown),
                          links=[Link(text, target) for text, target in links],
                          dismissible=dismissible, work_on_this=_work_on_this(title, message))
    except Exception:
        log.exception("Could not open the alert dialog: %s", title)
        targets = "\n".join(str(target) for _text, target in links)
        _fall_back_to_windows(title, f"{message}\n\n{targets}" if targets else message)
        return False


def _work_on_this(title: str, message: str) -> str:
    return new_session_link(CHECKOUT, "\n".join([
        f'He pressed Work on this on an Evolver error window titled "{title}". It said:',
        "",
        message,
        "",
        ("Load the debugging skill first. Find out why Evolver showed it, from Evolver's log, its Run History, the "
         "file times on disk and the transcripts of the Claude sessions at work at that minute: most of these errors "
         "come from another session's script, preview or test run, so find which Claude session changed the thing "
         "and tell that session what it broke. Fix the cause in Evolver's code only when no session did it, or do "
         "what the window asks of him wherever a session can. Tell him in one short "
         "message what you did and anything only he can do. Follow every law in ~/.claude/CLAUDE.md and "
         "~/.claude/engineering.md as any session does."),
    ]))


def _fall_back_to_windows(title: str, message: str) -> None:
    try:
        from app_support.win32 import show_error_popup  # noqa: PLC0415  (see the module docstring)

        show_error_popup(title, message)
    except Exception:
        log.exception("Could not open the Windows dialog either: %s", title)
