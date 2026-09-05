"""Every third-party import in backfill, gui, tasks, util is a dependency pyproject declares.

A launcher that imports a package nobody declared works on the machine that
happened to have it and dies on the merge gate, which installs exactly what the
pyproject says.  The gate is the family's (``app_support.dependencies``); what
is here is which packages are this repo's own.
"""
from __future__ import annotations

from pathlib import Path

from app_support.dependencies import assert_every_import_is_declared

ROOT = Path(__file__).resolve().parent.parent


def test_every_third_party_import_is_declared():
    assert_every_import_is_declared(
        ROOT, [ROOT / "backfill", ROOT / "gui", ROOT / "tasks", ROOT / "util",
               ROOT / "backfill_app.py", ROOT / "check_correspondence.py",
               ROOT / "check_duplicate_sizes.py", ROOT / "config.py", ROOT / "content_overlay.py",
               ROOT / "evolver.py", ROOT / "preview_branch.py", ROOT / "tray_app.py"],
        ROOT / "pyproject.toml", local=("backfill", "gui", "tasks", "util", "backfill_app", "check_correspondence",
               "check_duplicate_sizes", "config", "content_overlay", "evolver", "preview_branch",
               "tray_app"))
