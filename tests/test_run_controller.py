from __future__ import annotations

import ast
from unittest.mock import MagicMock, patch

import gui.run_controller
from tests.gui_support import build_evolver_app
from tests.product_sources import PROJECT_ROOT, gui_modules_imported_by, product_sources


def test_a_new_run_never_talks_to_the_last_runs_popup(request):
    app = build_evolver_app(request)
    app._window.hide()
    assert not app._window.isVisible(), "hidden, the window gets no popup of the new run's own"
    last_runs_popup = MagicMock()
    app._runs._progress_popup = last_runs_popup
    app._runs._on_finished(MagicMock(status="success", duration_seconds=12.0))
    last_runs_popup.reset_mock()

    with patch("gui.run_controller.PipelineWorker"):
        app._runs.start("scheduled")
        app._runs._on_finished(MagicMock(status="success", duration_seconds=12.0))

    assert last_runs_popup.mock_calls == []


def test_it_imports_nothing_that_reacts_to_its_runs():
    the_app_and_what_it_wires = {"gui.app", "gui.tray", "gui.scheduler", "gui.main_window"}

    assert gui_modules_imported_by(gui.run_controller) & the_app_and_what_it_wires == set(), (
        "the controller says what happened to a run; the tray, the schedule and the window react in the app")


def _callers_of(called: str) -> set[tuple[str, str]]:
    found = set()
    for relative in product_sources(PROJECT_ROOT):
        tree = ast.parse((PROJECT_ROOT / relative).read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found |= {(relative, function.name) for node in ast.walk(function)
                          if isinstance(node, ast.Call) and ast.unparse(node.func) == called}
    return found


def test_only_the_runs_upscale_stage_starts_an_encode():
    assert _callers_of("nonai_encode.start") == {
        ("tasks/nonai_upscale.py", "_start_next_queued_video"),
        ("tasks/nonai_request.py", "start_requested"),
    }, "an encode asked for starts on the next run, never from the window that asked"
    assert {path for path, _ in _callers_of("nonai_request.start_requested")} == {"tasks/nonai_upscale.py"}
    assert _callers_of("nonai_encode.launch") == set()
