from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


_TESTS_THAT_NAME_EVERYTHING_THE_PRODUCT_EXPORTS = "tests"
_TOOLING_THE_APP_NEVER_REACHES = "tools"


def _hidden_or_generated_such_as_claudes_whole_worktree_copies(name: str) -> bool:
    return name.startswith((".", "__"))


def product_sources(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in (_TESTS_THAT_NAME_EVERYTHING_THE_PRODUCT_EXPORTS, _TOOLING_THE_APP_NEVER_REACHES)
            and not _hidden_or_generated_such_as_claudes_whole_worktree_copies(name)
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
