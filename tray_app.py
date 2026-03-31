#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import atexit
import sys
import traceback as _traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG = Path(__file__).resolve().parent / "tray_crash.log"

_crash_logged = False


def _write_crash(header: str, detail: str):
    """Append a timestamped crash entry to the crash log."""
    global _crash_logged
    _crash_logged = True
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CRASH_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {header}\n{detail}")


def _on_exit():
    """Log clean exits so we can distinguish them from external kills."""
    if not _crash_logged:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stack = "".join(_traceback.format_stack())
        with CRASH_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] Clean exit\n{stack}")


def _install_excepthook():
    """Intercept unhandled exceptions before they reach PyQt6's qFatal/abort path.

    Without this, exceptions in Qt slots cause a silent C-level abort() with
    no Python traceback — especially under pythonw.exe which has no stderr.
    """
    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(_traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash("Unhandled exception in Qt callback:", text)
        sys.exit(1)
    sys.excepthook = _hook


def main():
    _install_excepthook()
    atexit.register(_on_exit)
    from gui.app import EvolverApp
    sys.exit(EvolverApp().run())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _write_crash("Startup crash:", _traceback.format_exc())
        sys.exit(1)
