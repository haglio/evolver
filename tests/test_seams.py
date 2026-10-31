"""The seams the first audit cut and the second found regrown (item 74), each held
by a ceiling that only comes down.

The tray app had been cut to its wiring and grew back to 43 methods, and the
non-AI upscale stage from 427 lines to 665, because every feature since was
written onto them beside the module that already stood for its part. A number
here fails the build before that happens again: the next feature gives its
glue a controller or a module of its own, or moves it onto the collaborator
that exists, rather than growing either of these.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT

pytestmark = pytest.mark.repo_check

EVOLVER_APP_METHODS_AT_MOST = 20
NONAI_UPSCALE_LINES_AT_MOST = 359


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


def test_the_upscale_stage_file_is_no_longer_than_its_ceiling():
    lines = Path(PROJECT_ROOT, "tasks/nonai_upscale.py").read_text(encoding="utf-8").count("\n")

    assert lines <= NONAI_UPSCALE_LINES_AT_MOST, (
        f"tasks/nonai_upscale.py is {lines} lines, over its ceiling of "
        f"{NONAI_UPSCALE_LINES_AT_MOST}: what the stage needs that is not the stage "
        "(the encode, the queue, the files, the video asked for, the progress) has a "
        "module of its own beside it; lower the ceiling when lines leave"
    )
