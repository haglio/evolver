"""A status is drawn as one colored symbol, the same one wherever it appears."""

import unittest

from PyQt6.QtWidgets import QApplication

from gui.status_symbols import mark_for

_app = QApplication.instance() or QApplication([])


class TestMarkFor(unittest.TestCase):

    def test_a_completed_stage_is_a_green_check(self):
        glyph, color = mark_for("completed")
        self.assertEqual(glyph, "✔")
        self.assertEqual(color.name(), "#30a030")

    def test_a_skipped_stage_is_an_empty_gray_circle(self):
        glyph, color = mark_for("skipped")
        self.assertEqual(glyph, "○")
        self.assertEqual(color.name(), "#808080")

    def test_a_held_back_stage_is_an_empty_gray_circle(self):
        """A low-disk hold must not draw the failure's mark. Free space stays
        low for days at a time, so a red ✘ for it puts a standing alarm on every
        run of those days over a condition with nothing in it to fix."""
        glyph, color = mark_for("warning")
        self.assertEqual(glyph, "○")
        self.assertEqual(color.name(), "#808080")
        self.assertEqual(mark_for("warning"), mark_for("skipped"))

    def test_an_errored_stage_is_a_red_cross(self):
        glyph, color = mark_for("error")
        self.assertEqual(glyph, "✘")
        self.assertEqual(color.name(), "#ff3c3c")

    def test_a_successful_run_draws_the_same_mark_as_a_completed_stage(self):
        """A run says "success" where a stage says "completed" — one verdict,
        two spellings, and no reason for the history list and the stage table to
        disagree about how it looks."""
        self.assertEqual(mark_for("success"), mark_for("completed"))

    def test_an_unknown_status_draws_nothing_rather_than_crashing(self):
        """Run records go back months; a status this build never wrote should
        leave the cell blank, not take the window down."""
        glyph, _ = mark_for("something_new")
        self.assertEqual(glyph, "")


if __name__ == "__main__":
    unittest.main()
