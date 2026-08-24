"""What this suite does on a machine that has no Win32.

Evolver binds Win32 while its modules are being imported, and the test package
itself resolved a dotted name through ``ctypes.windll`` before any test module
ran.  On an interpreter whose ``ctypes`` has no Windows half that was not a
handful of Windows tests failing -- it was nothing collected at all, so the
suite could say nothing about the code that has no platform in it.

This pins the other outcome.  The child interpreter below deletes the Windows
half of ``ctypes`` and then collects the suite, so it asks the same question on
Windows as it does anywhere else.
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

# Third-party packages that reach that surface while THEY are being imported,
# on Windows.  Taking it away leaves a machine that cannot exist -- one whose
# sys.platform still says win32, so platform-branching code takes the Windows
# branch with the Windows half gone.  That is the point for this repo's own
# modules, which is what the question is about; it is only noise for a
# dependency, so a dependency is imported while the surface is still there and
# is served from sys.modules afterwards.  A new one announces itself here, as a
# collection error naming its own file.
_DEPENDENCIES_THAT_NEED_WIN32_TO_IMPORT = ("qtawesome",)

_STRIP_WIN32_FROM_CTYPES = f"""
import ctypes, ctypes.wintypes
for _name in {_DEPENDENCIES_THAT_NEED_WIN32_TO_IMPORT!r}:
    try:
        __import__(_name)
    except ImportError:
        pass
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


class TestTheWholeSuite(unittest.TestCase):
    def test_it_collects_where_ctypes_has_no_windll(self):
        """Asked of the suite as a whole, and of pytest rather than of a list.

        A list of the modules that bind Win32 would only ever hold the ones
        somebody remembered to add, and the cost of forgetting one is not that
        module's tests -- it is every test module that reaches it, dropped from
        the run as a collection error nobody reads.  Collecting the suite is the
        question itself: the next module to bind Win32 at import fails here, on
        the commit that adds it.
        """
        result = run_without_the_win32_ctypes_surface(
            "import sys, pytest\n"
            "sys.exit(pytest.main(['--collect-only', '-q']))\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout[-4000:])


if __name__ == "__main__":
    unittest.main()
