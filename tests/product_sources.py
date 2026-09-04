"""The product's own Python files, for the tests that read the tree as text."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def product_sources(root: Path) -> list[str]:
    """Every product ``.py`` under *root*, as root-relative posix paths.

    The tests are left out (they name everything the product exports), and so
    is ``tools`` (developer tooling the suite drives, never reached from the
    app) and every hidden or generated tree -- ``.venv``, ``.git``, ``.claude``,
    which in the primary checkout holds whole worktree copies, ``__pycache__``.
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in ("tests", "tools") and not name.startswith((".", "__"))
        ]
        found += [
            Path(dirpath, name).relative_to(root).as_posix()
            for name in filenames if name.endswith(".py")
        ]
    return sorted(found)
