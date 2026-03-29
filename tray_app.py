#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import sys
import traceback
from pathlib import Path

CRASH_LOG = Path(__file__).resolve().parent / "tray_crash.log"


def main():
    from gui.app import EvolverApp
    sys.exit(EvolverApp().run())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        CRASH_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        sys.exit(1)
