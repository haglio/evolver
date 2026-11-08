from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources, strings_outside_docstrings

_OWNER = "util/library_records.py"

_SAME_WORD_ELSEWHERE = {("util/warm_gun.py", "action")}


def _module_level_strings(name: str) -> set[str]:
    tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
    return {node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)}


class TestWhereTheNamesComeFrom(unittest.TestCase):
    @pytest.mark.repo_check
    def test_a_name_another_module_already_declares_is_read_from_it_never_spelled_again(self):
        declared_elsewhere = {(name, value) for name in product_sources(PROJECT_ROOT) if name != _OWNER
                              for value in _module_level_strings(name)}
        tree = ast.parse(Path(PROJECT_ROOT, _OWNER).read_text(encoding="utf-8"))

        spelled_again = sorted(
            f"{_OWNER}:{node.lineno} {node.value!r}, declared in {name}"
            for node in strings_outside_docstrings(tree)
            for name, value in declared_elsewhere
            if value == node.value and (name, value) not in _SAME_WORD_ELSEWHERE)

        assert spelled_again == []


if __name__ == "__main__":
    unittest.main()
