"""What the whole suite runs under.

There was no conftest here at all, which is why twelve test modules each opened
by standing a QApplication up themselves. Importing `gui_support` builds the one
they now share, and does it before the first test module is imported.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import gui.app
from tests import gui_support  # noqa: F401  -- builds the shared QApplication


@pytest.fixture(autouse=True)
def _a_restart_never_starts_a_real_evolver(monkeypatch):
    """A press of Restart in a test would leave a real wait behind it, which starts
    this checkout's launcher, on his screen, once the run has ended."""
    monkeypatch.setattr(gui.app, "restart", SimpleNamespace(start_again_after=lambda pid, launcher: None))
