"""Windows error dialog helpers."""

import ctypes
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def _is_session_zero() -> bool:
    """Return True if running in the non-interactive Session 0 (S4U scheduled tasks, services)."""
    try:
        session_id = ctypes.c_ulong(0)
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        return session_id.value == 0
    except Exception:
        return False


def show_error_window(title: str, message: str) -> None:
    shown = False

    if not _is_session_zero():
        try:
            result = ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            shown = result != 0
            log.info("MessageBoxW returned %d (shown=%s)", result, shown)
        except Exception:
            log.exception("Failed to show Windows error dialog: %s", title)

    if shown:
        return

    msg_text = f"{title}. See evolver.log for details."
    sent = False

    for user in _get_active_users():
        if _send_msg(user, title, msg_text):
            sent = True
            break

    if not sent:
        sent = _send_msg("*", title, msg_text)

    if sent:
        log.error("Fallback notification sent via msg.exe: %s", title)
    else:
        log.error("Fallback notification failed via msg.exe: %s", title)


def _get_active_users() -> list[str]:
    users: list[str] = []
    try:
        result = subprocess.run(
            ["query", "user"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        log.exception("Failed to enumerate active users for msg.exe fallback")
        return users

    output = result.stdout or ""
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.replace(">", "").split()
        if not parts:
            continue
        username = parts[0]
        if username not in users:
            users.append(username)

    return users


def _send_msg(target: str, title: str, short_message: str) -> bool:
    try:
        result = subprocess.run(
            ["msg", target, "/TIME:5", f"{title}: {short_message}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        ok = result.returncode == 0
        log.info(
            "msg.exe target=%s rc=%s stdout=%r stderr=%r",
            target,
            result.returncode,
            stdout,
            stderr,
        )
        return ok
    except Exception:
        log.exception("msg.exe invocation failed for target=%s", target)
        return False
