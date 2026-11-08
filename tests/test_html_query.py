from __future__ import annotations

import ast
import sys

from tests.product_sources import PROJECT_ROOT


def test_it_is_the_standard_library_alone_and_knows_nothing_of_videos():
    tree = ast.parse((PROJECT_ROOT / "util" / "html_query.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}

    assert imported - sys.stdlib_module_names - {"__future__"} == set()
