from __future__ import annotations

import ast
import unittest

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources

pytestmark = pytest.mark.repo_check

_MUTATORS = frozenset({
    "add", "append", "clear", "difference_update", "discard", "extend",
    "insert", "intersection_update", "pop", "popitem", "remove", "reverse",
    "setdefault", "sort", "update",
})

def _result_types(trees: dict[str, ast.AST]) -> set[str]:
    return {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name.endswith("Result")
    }


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _rooted_at(node: ast.expr, name: str) -> bool:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return isinstance(node, ast.Name) and node.id == name


def _writes_through(body: list[ast.stmt], name: str) -> bool:
    for statement in body:
        for node in ast.walk(statement):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _MUTATORS):
                targets = [node.func.value]
            if any(isinstance(target, (ast.Attribute, ast.Subscript))
                   and _rooted_at(target, name) for target in targets):
                return True
    return False


def _out_parameters(tree: ast.AST, result_types: set[str]) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = node.args
        for argument in [*arguments.posonlyargs, *arguments.args,
                         *arguments.kwonlyargs]:
            if _annotation_name(argument.annotation) not in result_types:
                continue
            if _writes_through(node.body, argument.arg):
                found.append(node.name)
                break
    return found


def _trees() -> dict[str, ast.AST]:
    return {
        name: ast.parse((PROJECT_ROOT / name).read_text(encoding="utf-8"))
        for name in product_sources(PROJECT_ROOT)
    }


class TestStageResults(unittest.TestCase):
    def test_no_helper_writes_through_a_result_it_was_handed(self):
        trees = _trees()
        result_types = _result_types(trees)
        offenders = sorted(
            f"{name}:{function}"
            for name, tree in trees.items()
            for function in _out_parameters(tree, result_types)
        )

        assert offenders == [], (
            "return what the helper learned and let the caller that owns the result add it up: "
            "a helper writing into it hides which counters a call moves, and cannot be tested "
            "without building the stage's whole result")


if __name__ == "__main__":
    unittest.main()
