"""The launch smoke test: everything ``pythonw tray_app.py`` imports, imported.

The suite can be entirely green while the tray icon never appears, and this is
the gap. ``tray_app.py`` imports the app itself -- ``from gui.app import
EvolverApp`` -- *inside* ``main()``, after the crash-log hook is installed, so
a break anywhere under ``gui`` never touches a test that imports ``tray_app``
and stops at module level. ``tests/test_app_startup.py`` constructs
``EvolverApp`` but does it in the pytest process, where the suite's own imports
and ``tests/__init__.py``'s overlay pin have already run; the shortcut has
neither.

``pythonw`` is what makes a failure invisible rather than merely broken: it has
no console, so an import that fails before ``report_startup_crash`` can run
writes its traceback nowhere at all.

So this drives the launch's import phase the way the shortcut does: a fresh
interpreter, this repo as the working directory (which is what puts
``tray_app.py`` beside its ``gui`` and ``util`` packages), no inherited
``PYTHONPATH``, and the committed example overlay standing in for the
git-ignored local one -- which is also what a public checkout and CI have.

The walk that reads those imports off the AST and the three assertions that
replay them are ``app_support.launch_smoke``: seven repos carried a copy of the
same 200 lines, drifting. What stays here is the half that is this app's --
which files the launch executes, and how the shortcut starts an interpreter.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_support.launch_smoke import (
    assert_an_unresolvable_import_is_caught,
    assert_every_import_resolves,
    assert_the_walk_reached,
    launch_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# tray_app.py is a script beside the packages, not a package of its own, so no
# relative import can appear in the launch files and there is nothing to resolve
# them against.
PACKAGE = ""

# The files a launch runs: the tray script and the module holding the app --
# and the second entry point, the backfill tool the tray spawns DETACHED, whose
# ImportError otherwise writes its traceback nowhere while the menu item
# simply does nothing.
LAUNCH_FILES = (
    REPO_ROOT / "tray_app.py",
    REPO_ROOT / "gui" / "app.py",
    REPO_ROOT / "backfill_app.py",
    # The branch preview, whose whole point is being clicked by someone judging
    # a change: it is started by a vbs through pythonw exactly as the tray is,
    # so an import break in it is the same invisible dead icon -- and the one
    # that costs a review cycle rather than a run.
    REPO_ROOT / "preview_branch.py",
)

# Reached only from inside main(), so a module-level import test never saw it.
# Asserted present, so a walk that silently found nothing -- a renamed file, a
# parse that returned an empty tree -- cannot pass as a clean launch.
_REACHED_ONLY_FROM_INSIDE_MAIN = ("gui.app",)


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way the shortcut runs ``tray_app.py``.

    Its own directory is what Python puts on ``sys.path`` for a script, and it
    is what makes ``gui`` and ``util`` importable, so the working directory is
    the whole path story -- any ``PYTHONPATH`` a developer or pytest happens to
    be carrying is dropped, because the shortcut does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    driver = "\n".join(
        [
            # Before anything that reads content at import time: a public
            # checkout has only the committed example, so that is what the
            # launch has to come up on.
            "import content_overlay as _content",
            "_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT",
            *statements,
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", driver],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_launch_imports_everything_it_names():
    """Failing here means the tray icon never appears and nothing says why:
    pythonw has no console, and the failure precedes the crash-log hook."""
    assert_every_import_resolves(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES))


def test_the_walk_reaches_the_imports_buried_in_main():
    """The guard above is only worth anything if the walk found the lazy one --
    which is the entire app."""
    assert_the_walk_reached(
        launch_imports(PACKAGE, LAUNCH_FILES), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    assert_an_unresolvable_import_is_caught(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES),
        "gui.app")


# Restart being a launch of the same script on the same interpreter is pinned
# behaviourally in test_app_startup.py's TestRestart (the Popen argv), not by
# grepping gui/app.py's source, which broke on any reformat.
