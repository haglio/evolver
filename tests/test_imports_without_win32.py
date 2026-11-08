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

# With ctypes' Windows half gone sys.platform still says win32, so a package's own Windows
# branch would fail as it imports: these are imported while the Win32 surface still exists,
# then served from sys.modules. pytest reports a new one as a collection error in its own file.
_DEPENDENCIES_THAT_NEED_WIN32_TO_IMPORT = ("app_support.processes",)

# app_support reads the checkout by running git inside a Windows job object, so the reading is
# taken while the surface exists and served from app_support's cache afterwards.
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


# A shim on PYTHONPATH can put ctypes' Windows half back in, the way a non-Windows developer's run does.
def _environ_without_pythonpath(environ):
    return {name: value for name, value in environ.items() if name != "PYTHONPATH"}


def run_without_the_win32_ctypes_surface(body):
    return subprocess.run(
        [sys.executable, "-c", _STRIP_WIN32_FROM_CTYPES + body],
        cwd=str(REPO_DIR), env=_environ_without_pythonpath(os.environ),
        capture_output=True, text=True, timeout=180, check=False,
    )


class TestCollectingTheWholeSuiteNotAListOfModules(unittest.TestCase):
    def test_no_test_module_drops_out_where_ctypes_has_no_windll(self):
        result = run_without_the_win32_ctypes_surface(
            "import sys, pytest\n"
            "sys.exit(pytest.main(['--collect-only', '-q', '--no-cov']))\n"
        )

        assert result.returncode == 0, result.stdout[-4000:]


if __name__ == "__main__":
    unittest.main()
