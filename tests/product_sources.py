from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


_NOT_THE_PRODUCT = ("tests", "tools")


def _hidden_or_generated(name: str) -> bool:
    return name.startswith((".", "__"))


def product_sources(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in _NOT_THE_PRODUCT and not _hidden_or_generated(name)
        ]
        found += [
            Path(dirpath, name).relative_to(root).as_posix()
            for name in filenames if name.endswith(".py")
        ]
    return sorted(found)


def config_names_read(*modules: str) -> set[str]:
    found: set[str] = set()
    for name in modules:
        tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        found |= {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "config"
        }
    return found


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
