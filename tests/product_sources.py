"""The product's own Python files, and the strings they hold, for the tests that read the tree as text."""
from __future__ import annotations

import ast
import os
from collections.abc import Iterator
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


def strings_outside_docstrings(tree: ast.AST) -> Iterator[ast.Constant]:
    docstrings = {
        id(scope.body[0].value)
        for scope in ast.walk(tree)
        if isinstance(scope, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and scope.body and isinstance(scope.body[0], ast.Expr)
        and isinstance(scope.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node
