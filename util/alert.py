# Qt is imported inside the call: the startup crash reporter comes through here when PySide6 may be what failed to import.

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from app_support.claude_sessions import new_session_link

from local_state import CHECKOUT, LOCAL_STATE_DIR

log = logging.getLogger(__name__)

ICON_FILE = CHECKOUT / "icon.ico"
ERRORS_SHOWN_FILE = LOCAL_STATE_DIR / "errors_shown.json"


def show_error(title: str, message: str, links: Sequence[tuple[str, Path]] = (), *,
               dismissible: bool = False, same_error: str | None = None, work_on_this: bool = True) -> bool:
    if work_on_this and _shown_before(title, message if same_error is None else same_error):
        log.info("Not showing %s again: the same error's window was shown before", title)
        return False
    return _show(title, message, links, dismissible=dismissible, work_on_this=work_on_this)


def show_warning(title: str, message: str) -> bool:
    from shared_ui.alert import Level  # noqa: PLC0415  (see the module docstring)

    return _show(title, message, (), dismissible=False, work_on_this=True, level=Level.WARNING)


def _show(title: str, message: str, links: Sequence[tuple[str, Path]], *, dismissible: bool, work_on_this: bool,
          **look: object) -> bool:
    try:
        from shared_ui.alert import Link, show_alert  # noqa: PLC0415  (see the module docstring)
        from shared_ui.preview_icon import app_icon  # noqa: PLC0415  (see the module docstring)

        from util.preview import shown_as  # noqa: PLC0415  (see the module docstring)

        shown = shown_as()
        return show_alert(title, message, icon=ICON_FILE if shown is None else app_icon(ICON_FILE, shown),
                          links=[Link(text, target) for text, target in links],
                          dismissible=dismissible,
                          work_on_this=_work_on_this(title, message) if work_on_this else None, **look)
    except Exception:
        log.exception("Could not open the alert dialog: %s", title)
        targets = "\n".join(str(target) for _text, target in links)
        _fall_back_to_windows(title, f"{message}\n\n{targets}" if targets else message)
        return False


def _shown_before(title: str, error_said: str) -> bool:
    try:
        record = ERRORS_SHOWN_FILE
        error = hashlib.sha256(f"{title}\n{error_said}".encode()).hexdigest()
        shown = set(json.loads(record.read_text(encoding="utf-8"))) if record.exists() else set()
        if error in shown:
            return True
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(sorted(shown | {error})), encoding="utf-8")
    except Exception:
        log.exception("Could not read or write the errors already shown: %s", title)
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
