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
PACKAGE = ""

LAUNCH_FILES = (
    REPO_ROOT / "tray_app.py",
    REPO_ROOT / "gui" / "app.py",
    REPO_ROOT / "backfill_app.py",
    REPO_ROOT / "review_trash_app.py",
)

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
        check=False,
    )


def test_the_launch_imports_everything_it_names():
    assert_every_import_resolves(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES))


def test_the_walk_reaches_the_imports_buried_in_main():
    assert_the_walk_reached(
        launch_imports(PACKAGE, LAUNCH_FILES), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    assert_an_unresolvable_import_is_caught(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES),
        "gui.app")

