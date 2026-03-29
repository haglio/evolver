#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import sys

from gui.app import EvolverApp

if __name__ == "__main__":
    sys.exit(EvolverApp().run())
