"""Evolver wears the family's look: shared_ui's colors, marks, lettering and spacing, none of its own."""
from __future__ import annotations

from pathlib import Path

from shared_ui.look_guard import assert_the_look_is_shared_uis

_CHECKOUT = Path(__file__).resolve().parents[1]
_PACKAGES = ("gui", "backfill", "review_weird", "tasks", "util", "tools")
# The Stats chart tells its 19 stages apart by colors of their own, which its owner chose to keep (2026-10-24).
_WHERE_THE_STAGES_COLORS_ARE = _CHECKOUT / "tasks" / "stages.py"


def test_everything_evolver_draws_with_comes_from_shared_ui():
    modules = [*sorted(_CHECKOUT.glob("*.py")),
               *(path for package in _PACKAGES for path in sorted((_CHECKOUT / package).rglob("*.py")))]
    assert_the_look_is_shared_uis(_CHECKOUT, [path for path in modules if path != _WHERE_THE_STAGES_COLORS_ARE])
