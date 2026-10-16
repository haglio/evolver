"""Starting Evolver again only once this copy has ended, through its launcher.

The launcher brings the checkout up to what has shipped before it starts the app,
which the production updater does only while nothing runs out of the checkout's
venv: so the wait runs on the plain interpreter, never out of that venv.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_THEN_THE_LAUNCHER = """\
import ctypes, subprocess, sys
kernel32 = ctypes.WinDLL("kernel32")
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
ending = kernel32.OpenProcess(0x00100000, False, int(sys.argv[1]))
if ending:
    kernel32.WaitForSingleObject(ending, 120000)
subprocess.run(["wscript.exe", sys.argv[2]])
"""


def start_again_after(pid: int, launcher: Path, *, popen=subprocess.Popen) -> None:
    popen([str(Path(sys._base_executable).with_name("pythonw.exe")), "-c", _THEN_THE_LAUNCHER,
           str(pid), str(launcher)],
          creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
