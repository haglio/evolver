"""A stage's result is filled in by the stage, and by nothing it calls.

Every stage returns a dataclass of counters. Fifteen helpers used to take that
dataclass and write into it instead of returning what they found, so a reader
could not tell from a call site which counters a call moved, and no helper
could be tested without building the stage's whole result type. It is the same
shared mutable state a global is, scoped to one call tree — and it is what kept
the non-AI supervision welded to its stage.

Held as a gate rather than by care because an out-parameter is ordinary Python
and raises nothing: the helper compiles, the stage passes, and the coupling is
invisible until someone tries to move the helper. A helper may still *read* a
result — formatting a message out of one is what a result is for — but the
counters go up in the function that owns them.

The ledger below is what is left, held exactly rather than as a ceiling: a
conversion that does not lower it fails here, and so does a new out-parameter
written while it is still non-empty. It is named by function rather than by
line so that editing around one does not move it. It ends at nothing, and the
ledger goes with it.
"""
from __future__ import annotations

import ast
import unittest

from tests.product_sources import PROJECT_ROOT, product_sources

# Methods that change what they are called on. A call to one of these on a
# result's field is the same write as an assignment, spelled through the list.
_MUTATORS = frozenset({
    "add", "append", "clear", "difference_update", "discard", "extend",
    "insert", "intersection_update", "pop", "popitem", "remove", "reverse",
    "setdefault", "sort", "update",
})

# Helpers still handed their stage's result to fill in. Take one off in the
# commit that converts it.
STILL_AN_OUT_PARAMETER = [
    "tasks/bookmarks_sync.py:_load_and_prune_rows",
    "tasks/bookmarks_sync.py:_read_urls",
    "tasks/nonai_upscale.py:_conclude",
    "tasks/nonai_upscale.py:_report_progress",
    "tasks/nonai_upscale.py:_start_next_candidate",
    "tasks/nonai_upscale.py:_stop_in_flight",
    "tasks/nonai_upscale.py:_supervise",
    "tasks/purge_weird.py:_purge_pile",
    "tasks/reference_sync.py:_reconcile",
    "tasks/scripts_sync.py:_copy_missing_variant_scripts",
    "tasks/scripts_sync.py:_discard_or_keep_duplicate",
    "tasks/scripts_sync.py:_follow_retired_videos",
    "tasks/scripts_sync.py:_rehome_to_library_variant",
    "tasks/stray_files.py:_rehome_script",
    "tasks/stray_files.py:_repair_extension",
    "tasks/stray_files.py:_report",
    "tasks/watch_weights.py:_apply_phone_favorites",
]


def _result_types(trees: dict[str, ast.AST]) -> set[str]:
    """The stage-result dataclasses this repo declares, by name."""
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
    """Whether *node* is an attribute chain hanging off the parameter *name*."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return isinstance(node, ast.Name) and node.id == name


def _writes_through(body: list[ast.stmt], name: str) -> bool:
    """Whether *body* writes through the parameter *name*."""
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
    """The functions in *tree* that write through a result they were handed."""
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

        self.assertEqual(
            offenders,
            STILL_AN_OUT_PARAMETER,
            "return what the helper learned and let the caller that owns the "
            "result add it up, then take it off the ledger",
        )


if __name__ == "__main__":
    unittest.main()
