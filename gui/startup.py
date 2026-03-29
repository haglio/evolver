"""Windows Startup folder shortcut management."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_dir() / "Evolver.lnk"


def is_registered() -> bool:
    return _shortcut_path().exists()


def register_startup():
    """Create a .lnk shortcut in the Windows Startup folder."""
    import win32com.client

    shortcut_path = _shortcut_path()
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.TargetPath = sys.executable  # pythonw.exe or python.exe
    shortcut.Arguments = str(Path(__file__).resolve().parent.parent / "tray_app.py")
    shortcut.WorkingDirectory = str(Path(__file__).resolve().parent.parent)
    shortcut.Description = "Evolver Tray Application"
    shortcut.save()


def unregister_startup():
    """Remove the startup shortcut if it exists."""
    path = _shortcut_path()
    if path.exists():
        path.unlink()
