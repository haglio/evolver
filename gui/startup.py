"""Windows Startup folder shortcut management.

Creates a proper .lnk shortcut using a temporary VBScript, avoiding any
dependency on pywin32.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_dir() / "Evolver.lnk"


def is_registered() -> bool:
    return _shortcut_path().exists()


def _vbs_string(value) -> str:
    """*value* as a VBScript string literal: a quote inside one is written twice."""
    return '"' + str(value).replace('"', '""') + '"'


def register_startup():
    """Create a .lnk shortcut in the Windows Startup folder."""
    project_dir = Path(__file__).resolve().parent.parent
    target = sys.executable
    arguments = str(project_dir / "tray_app.py")
    working_dir = str(project_dir)
    shortcut_path = str(_shortcut_path())

    vbs = (
        'Set oWS = WScript.CreateObject("WScript.Shell")\n'
        f'Set oLink = oWS.CreateShortCut({_vbs_string(shortcut_path)})\n'
        f'oLink.TargetPath = {_vbs_string(target)}\n'
        f'oLink.Arguments = {_vbs_string(arguments)}\n'
        f'oLink.WorkingDirectory = {_vbs_string(working_dir)}\n'
        'oLink.Description = "Evolver Tray Application"\n'
        'oLink.Save\n'
    )

    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False, encoding="utf-8") as f:
        f.write(vbs)
        vbs_path = f.name

    try:
        subprocess.run(["cscript", "//Nologo", vbs_path], check=True, capture_output=True)
    finally:
        Path(vbs_path).unlink(missing_ok=True)


def unregister_startup():
    """Remove the startup shortcut if it exists."""
    path = _shortcut_path()
    if path.exists():
        path.unlink()
