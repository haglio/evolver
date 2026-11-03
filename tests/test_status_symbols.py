from __future__ import annotations

import inspect
import unittest

from shared_ui.colors import GREEN, RED, TEXT_MUTED

from gui import status_symbols
from gui.status_symbols import status_icon, symbol_for


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
        symbol, color = symbol_for("warning")
        assert symbol == "circle"
        assert color.name() == TEXT_MUTED.name()
        assert symbol_for("warning") == symbol_for("skipped")

    def test_an_errored_stage_is_a_red_cross(self):
        symbol, color = symbol_for("error")
        assert symbol == "cross"
        assert color.name() == RED.name()

    def test_a_successful_run_draws_the_same_mark_as_a_completed_stage(self):
        assert symbol_for("success") == symbol_for("completed")

    def test_an_unknown_status_draws_nothing_rather_than_crashing(self):
        symbol, _ = symbol_for("something_new")
        assert symbol == ""


class TestAStatusWithNoMark:
    def test_it_gives_an_icon_with_nothing_drawn(self):
        assert status_icon("never heard of it").isNull()


if __name__ == "__main__":
    unittest.main()


class TestMarkIconSurface(unittest.TestCase):
    def test_the_mark_is_drawn_at_one_size(self):
        assert list(inspect.signature(status_symbols.status_icon).parameters) == ["status"]
        assert status_symbols.status_icon("error").availableSizes()[0].width() == status_symbols._MARK_PX
