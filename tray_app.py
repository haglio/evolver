#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG = Path(__file__).resolve().parent / "tray_crash.log"


def _write_crash(header: str, detail: str):
    """Write a timestamped crash entry to the crash log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    CRASH_LOG.write_text(f"[{timestamp}] {header}\n{detail}", encoding="utf-8")


def _install_excepthook():
    """Intercept unhandled exceptions before they reach PyQt6's qFatal/abort path.

    Without this, exceptions in Qt slots cause a silent C-level abort() with
    no Python traceback — especially under pythonw.exe which has no stderr.
    """
    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash("Unhandled exception in Qt callback:", text)
        sys.exit(1)
    sys.excepthook = _hook


def main():
    _install_excepthook()
    from gui.app import EvolverApp
    sys.exit(EvolverApp().run())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _write_crash("Startup crash:", traceback.format_exc())
        sys.exit(1)
