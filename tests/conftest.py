from __future__ import annotations

import pytest

import gui.app
from tests import gui_support  # noqa: F401  -- builds the shared QApplication


@pytest.fixture(autouse=True)
def _a_restart_never_starts_a_real_evolver(monkeypatch):
    monkeypatch.setattr(gui.app.production_update, "start_again_after", lambda pid, launcher: None)
