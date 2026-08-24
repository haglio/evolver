"""What this suite does on a machine that has no Win32.

Evolver binds Win32 while its modules are being imported, and the test package
itself resolves a dotted name through ``ctypes.windll`` before any test module
runs.  On an interpreter whose ``ctypes`` has no Windows half that is not a
handful of Windows tests failing -- it is nothing collected at all, so the suite
cannot say anything about the code that has no platform in it.

These cases pin the other outcome.  The child interpreters below delete the
Windows half of ``ctypes`` before importing anything, so each case asks the same
question on Windows as it does anywhere else.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

# The names ``ctypes`` grows only on Windows, and that the modules under test
# reach for while they are being imported.
_WIN32_CTYPES_NAMES = (
    "windll", "oledll", "WinDLL", "OleDLL", "WINFUNCTYPE", "HRESULT",
    "get_last_error", "set_last_error",
)

_STRIP_WIN32_FROM_CTYPES = f"""
import ctypes, ctypes.wintypes
for _name in {_WIN32_CTYPES_NAMES!r}:
    if hasattr(ctypes, _name):
        delattr(ctypes, _name)
"""


def run_without_the_win32_ctypes_surface(body):
    """Run *body* in a child whose ``ctypes`` has had its Windows half removed.

    ``PYTHONPATH`` is dropped so the child cannot pick up a shim that fakes that
    surface back in, the way a run on a developer's non-Windows machine does.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", _STRIP_WIN32_FROM_CTYPES + body],
        cwd=str(REPO_DIR), env=env, capture_output=True, text=True, timeout=180,
    )


# The modules that reach Win32 while they are being imported, and so decide for
# every test module that reaches them whether it can be collected at all.
_MUST_IMPORT_WITHOUT_WIN32 = (
    "util.processes",
    "tests.test_processes",
)


class TestTheModulesThatBindWin32(unittest.TestCase):
    def test_they_import_where_ctypes_has_no_windll(self):
        for module in _MUST_IMPORT_WITHOUT_WIN32:
            with self.subTest(module=module):
                result = run_without_the_win32_ctypes_surface(f"import {module}\n")

                self.assertEqual(result.returncode, 0, result.stderr)


class TestTheTestPackageItself(unittest.TestCase):
    def test_it_imports_where_ctypes_has_no_windll(self):
        """Every test module in this repo runs ``tests/__init__.py`` first.

        So a name it resolves through ``ctypes.windll`` is not one file's
        problem: it is every collected test in the run, at once.
        """
        result = run_without_the_win32_ctypes_surface("import tests\n")

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
