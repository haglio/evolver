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
PACKAGE_OF_A_SCRIPT_BESIDE_THE_PACKAGES = ""

_TOOLS_THE_TRAY_STARTS_DETACHED_WHOSE_IMPORT_ERRORS_GO_NOWHERE = (
    REPO_ROOT / "backfill_app.py",
    REPO_ROOT / "review_trash_app.py",
)

LAUNCH_FILES = (
    REPO_ROOT / "tray_app.py",
    REPO_ROOT / "gui" / "app.py",
    *_TOOLS_THE_TRAY_STARTS_DETACHED_WHOSE_IMPORT_ERRORS_GO_NOWHERE,
)

_REACHED_ONLY_FROM_INSIDE_MAIN = ("gui.app",)


def _run_as_the_shortcut_does_from_the_repo_without_pythonpath_on_the_example_overlay(statements: list[str]) -> subprocess.CompletedProcess:
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


def test_every_import_the_launch_makes_resolves_or_pythonw_shows_no_icon_and_no_reason():
    assert_every_import_resolves(
        _run_as_the_shortcut_does_from_the_repo_without_pythonpath_on_the_example_overlay, launch_imports(PACKAGE_OF_A_SCRIPT_BESIDE_THE_PACKAGES, LAUNCH_FILES))


def test_the_walk_reaches_the_imports_buried_in_main():
    assert_the_walk_reached(
        launch_imports(PACKAGE_OF_A_SCRIPT_BESIDE_THE_PACKAGES, LAUNCH_FILES), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    assert_an_unresolvable_import_is_caught(
        _run_as_the_shortcut_does_from_the_repo_without_pythonpath_on_the_example_overlay, launch_imports(PACKAGE_OF_A_SCRIPT_BESIDE_THE_PACKAGES, LAUNCH_FILES),
        "gui.app")

