from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

_WIN32_CTYPES_NAMES = (
    "windll", "oledll", "WinDLL", "OleDLL", "WINFUNCTYPE", "HRESULT",
    "get_last_error", "set_last_error",
)

# Imported while the Win32 surface still exists, then served from sys.modules.
_DEPENDENCIES_THAT_NEED_WIN32_TO_IMPORT = ("app_support.processes",)

_CHECKOUT_READ_WHILE_IMPORTING = REPO_DIR / "util" / "provenance.py"

_STRIP_WIN32_FROM_CTYPES = f"""
import ctypes, ctypes.wintypes
for _name in {_DEPENDENCIES_THAT_NEED_WIN32_TO_IMPORT!r}:
    try:
        __import__(_name)
    except ImportError:
        pass
import app_support.provenance
app_support.provenance.stamp("evolver", anchor={str(_CHECKOUT_READ_WHILE_IMPORTING)!r})
for _name in {_WIN32_CTYPES_NAMES!r}:
    if hasattr(ctypes, _name):
        delattr(ctypes, _name)
"""


def run_without_the_win32_ctypes_surface(body):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", _STRIP_WIN32_FROM_CTYPES + body],
        cwd=str(REPO_DIR), env=env, capture_output=True, text=True, timeout=180,
        check=False,
    )


class TestTheWholeSuite(unittest.TestCase):
    def test_it_collects_where_ctypes_has_no_windll(self):
        result = run_without_the_win32_ctypes_surface(
            "import sys, pytest\n"
            "sys.exit(pytest.main(['--collect-only', '-q', '--no-cov']))\n"
        )

        assert result.returncode == 0, result.stdout[-4000:]


if __name__ == "__main__":
    unittest.main()
