"""The seams the first audit cut and the second found regrown (item 74), each held
by a ceiling that only comes down.

The tray app had been cut to its wiring and grew back to 43 methods because
every feature since was written onto it beside the controller that already
stood for its part. A number here fails the build before that happens again:
the next feature gives its glue a controller of its own, or moves it onto the
collaborator that exists, rather than a method here.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT

pytestmark = pytest.mark.repo_check

EVOLVER_APP_METHODS_AT_MOST = 20


def _methods_of(class_name: str, source: str) -> list[str]:
    tree = ast.parse(Path(PROJECT_ROOT, source).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    raise AssertionError(f"{source} no longer defines {class_name}")


def test_the_tray_app_holds_no_more_methods_than_its_ceiling():
    methods = _methods_of("EvolverApp", "gui/app.py")

    assert len(methods) <= EVOLVER_APP_METHODS_AT_MOST, (
        f"EvolverApp has {len(methods)} methods, over its ceiling of "
        f"{EVOLVER_APP_METHODS_AT_MOST}: a feature's glue goes onto the collaborator "
        "that already has its part (the run, queue and branch-session controllers), "
        "or gets a controller of its own; lower the ceiling when a method leaves"
    )
