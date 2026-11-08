from __future__ import annotations

from unittest.mock import MagicMock, patch

import gui.run_controller
from tests.gui_support import build_evolver_app
from tests.product_sources import gui_modules_imported_by


def test_a_run_started_while_the_window_is_hidden_never_talks_to_the_last_runs_closed_popup(request):
    app = build_evolver_app(request)
    last_runs_popup = MagicMock()
    app._runs._progress_popup = last_runs_popup
    app._runs._on_finished(MagicMock(status="success", duration_seconds=12.0))
    last_runs_popup.reset_mock()

    with patch("gui.run_controller.PipelineWorker"):
        app._runs.start("scheduled")
        app._runs._on_finished(MagicMock(status="success", duration_seconds=12.0))

    assert last_runs_popup.mock_calls == []


def test_it_announces_what_happened_to_a_run_and_leaves_the_reactions_to_the_app():
    the_app_and_what_it_wires = {"gui.app", "gui.tray", "gui.scheduler", "gui.main_window"}

    assert gui_modules_imported_by(gui.run_controller) & the_app_and_what_it_wires == set()
