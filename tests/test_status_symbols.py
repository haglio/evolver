"""A status is drawn as one colored symbol, the same one wherever it appears."""
from __future__ import annotations

import inspect
import unittest

from shared_ui.colors import GREEN, RED, TEXT_MUTED

from gui import status_symbols
from gui.status_symbols import symbol_for


class TestMarkFor(unittest.TestCase):

    def test_a_completed_stage_is_a_green_check(self):
        symbol, color = symbol_for("completed")
        assert symbol == "check"
        assert color.name() == GREEN.name()

    def test_a_skipped_stage_is_an_empty_gray_circle(self):
        symbol, color = symbol_for("skipped")
        assert symbol == "circle"
        assert color.name() == TEXT_MUTED.name()

    def test_a_held_back_stage_is_an_empty_gray_circle(self):
        """A low-disk hold must not draw the failure's mark. Free space stays
        low for days at a time, so a red ✘ for it puts a standing alarm on every
        run of those days over a condition with nothing in it to fix."""
        symbol, color = symbol_for("warning")
        assert symbol == "circle"
        assert color.name() == TEXT_MUTED.name()
        assert symbol_for("warning") == symbol_for("skipped")

    def test_an_errored_stage_is_a_red_cross(self):
        symbol, color = symbol_for("error")
        assert symbol == "cross"
        assert color.name() == RED.name()

    def test_a_successful_run_draws_the_same_mark_as_a_completed_stage(self):
        """A run says "success" where a stage says "completed" — one verdict,
        two spellings, and no reason for the history list and the stage table to
        disagree about how it looks."""
        assert symbol_for("success") == symbol_for("completed")

    def test_an_unknown_status_draws_nothing_rather_than_crashing(self):
        """Run records go back months; a status this build never wrote should
        leave the cell blank, not take the window down."""
        symbol, _ = symbol_for("something_new")
        assert symbol == ""


if __name__ == "__main__":
    unittest.main()


class TestMarkIconSurface(unittest.TestCase):
    def test_the_mark_is_drawn_at_one_size(self):
        """One view draws these icons and it has never asked for another size."""
        assert list(inspect.signature(status_symbols.status_icon).parameters) == ["status"]
        assert status_symbols.status_icon("error").availableSizes()[0].width() == status_symbols._MARK_PX
