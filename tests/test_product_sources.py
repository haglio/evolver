from __future__ import annotations

import ast

from tests.product_sources import product_sources, strings_outside_docstrings
from tests.temp_helpers import workspace_temp_dir

_A_MODULE = '''
"""The module's own docstring."""
LABEL = "a label"


class Panel:
    """The class's docstring."""

    def title(self):
        """The method's docstring."""
        return "a title"
'''


def test_a_modules_strings_are_its_literals_and_none_of_its_docstrings():
    strings = {node.value for node in strings_outside_docstrings(ast.parse(_A_MODULE))}

    assert strings == {"a label", "a title"}


def test_the_product_is_neither_its_tests_its_tools_nor_a_worktree_copy_under_dot_claude():
    with workspace_temp_dir() as root:
        for module in ("gui/app.py", "tests/test_app.py", "tools/run_stage.py",
                       ".claude/worktrees/alpha/gui/app.py", "__pycache__/app.py"):
            (root / module).parent.mkdir(parents=True, exist_ok=True)
            (root / module).write_text("", encoding="utf-8")

        assert product_sources(root) == ["gui/app.py"]
