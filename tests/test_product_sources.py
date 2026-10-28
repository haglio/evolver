from __future__ import annotations

import ast

from tests.product_sources import strings_outside_docstrings

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
