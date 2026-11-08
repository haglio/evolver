from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources

pytestmark = pytest.mark.repo_check

_OURS = (
    "check_correspondence", "check_duplicate_sizes",
    "config", "content_overlay", "evolver", "gui", "review_trash", "review_trash_app", "tasks",
    "tray_app", "util", "vulture_whitelist",
)

ALLOWED = {
    "check_correspondence": {"config", "util"},
    "check_duplicate_sizes": {"config", "util"},
    "config": {"content_overlay"},
    "evolver": {"check_correspondence", "check_duplicate_sizes", "config",
                "tasks", "util"},
    "gui": {"config", "evolver", "util"},
    "review_trash": {"config", "util"},
    "review_trash_app": {"evolver", "gui", "review_trash"},
    "tasks": {"config", "util"},
    "tray_app": {"gui", "util"},
    "util": {"config"},
}


def _package_of(dotted: str) -> str | None:
    head = dotted.split(".", maxsplit=1)[0]
    return head if head in _OURS else None


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _edges() -> tuple[dict[str, set[str]], list[str]]:
    used: dict[str, set[str]] = {}
    unlisted: list[str] = []
    for name in product_sources(PROJECT_ROOT):
        source = _package_of(name.replace("/", ".").removesuffix(".py"))
        if source is None:
            continue
        tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        for imported in _imports(tree):
            if _package_of(imported) in (None, source):
                continue
            allowed = ALLOWED.get(source, set())
            match = next(
                (prefix for prefix in allowed
                 if imported == prefix or imported.startswith(prefix + ".")),
                None,
            )
            if match is None:
                unlisted.append(f"{name}: {imported}")
            else:
                used.setdefault(source, set()).add(match)
    return used, unlisted


class TestLayering(unittest.TestCase):
    def test_no_package_imports_one_it_is_not_allowed_to_so_only_the_pipeline_touches_the_library(self):
        _used, unlisted = _edges()

        assert sorted(unlisted) == [], "an import across a layer boundary that nothing declares -- either it belongs in ALLOWED with a reason, or it is the wrong way round"

    def test_every_declared_edge_is_one_something_actually_uses(self):
        used, _unlisted = _edges()

        assert used == ALLOWED


if __name__ == "__main__":
    unittest.main()
