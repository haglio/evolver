"""How the tray app records the way it died, for the times it dies unwatched.

Under pythonw.exe there is no console and no stderr, so an unhandled exception
is a silent abort. Everything here exists to leave a written trace of it.

This lives in its own module rather than in tray_app.py because tray_app.py is
run as a script: importing it from elsewhere makes a *second* module object, so
the flag one copy sets is not the flag the other copy reads, and every entry
written from the GUI was followed by a "Clean exit" line that was not true.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG = Path(__file__).resolve().parent.parent / "tray_crash.log"

_crash_logged = False


def write_crash(header: str, detail: str) -> None:
    """Append a timestamped crash entry, and suppress the atexit 'Clean exit' line."""
    global _crash_logged
    _crash_logged = True
    _append(header, detail)


def write_info(header: str, detail: str) -> None:
    """Append a timestamped entry for something that is not a crash."""
    _append(header, detail)


def on_exit() -> None:
    """Log clean exits so we can distinguish them from external kills."""
    if not _crash_logged:
        _append("Clean exit", "".join(traceback.format_stack()))


def install_excepthook() -> None:
    """Intercept unhandled exceptions before they reach PyQt6's qFatal/abort path.

    Without this, exceptions in Qt slots cause a silent C-level abort() with
    no Python traceback — especially under pythonw.exe which has no stderr.
    """
    def _hook(exc_type, exc_value, exc_tb):
        write_crash(
            "Unhandled exception in Qt callback:",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.exit(1)

    sys.excepthook = _hook


def _append(header: str, detail: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CRASH_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {header}\n{detail}")
