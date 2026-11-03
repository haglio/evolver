from __future__ import annotations

import ast
import unittest

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources

pytestmark = pytest.mark.repo_check

_QUALIFIED_ONLY = frozenset({"read", "update", "write"})


def _bare_verb_imports(tree: ast.AST) -> list[str]:
    return [
        f"{node.lineno}:{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "util.sidecar"
        for alias in node.names
        if alias.name in _QUALIFIED_ONLY
    ]


class TestOneWordPerConcept(unittest.TestCase):
    def test_the_sidecars_verbs_are_reached_through_their_module(self):
        offenders = sorted(
            f"{name}:{site}"
            for name in product_sources(PROJECT_ROOT)
            for site in _bare_verb_imports(
                ast.parse((PROJECT_ROOT / name).read_text(encoding="utf-8")))
        )

        assert offenders == [], "`from util import sidecar` and `sidecar.read(...)`, so the verb says what it reads"


if __name__ == "__main__":
    unittest.main()
