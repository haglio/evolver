from __future__ import annotations

from pathlib import Path

import pytest
from shared_ui.look_guard import assert_the_look_is_shared_uis

pytestmark = pytest.mark.repo_check

_CHECKOUT = Path(__file__).resolve().parents[1]
_PACKAGES = ("gui", "backfill", "review_trash", "tasks", "util", "tools")
_STATS_CHART_STAGE_COLORS_KEPT_BY_CHOICE = _CHECKOUT / "evolver.py"


def test_everything_evolver_draws_with_comes_from_shared_ui():
    modules = [*sorted(_CHECKOUT.glob("*.py")),
               *(path for package in _PACKAGES for path in sorted((_CHECKOUT / package).rglob("*.py")))]
    assert_the_look_is_shared_uis(_CHECKOUT, [path for path in modules if path != _STATS_CHART_STAGE_COLORS_KEPT_BY_CHOICE])
