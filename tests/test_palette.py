"""The colors are the family's, not the ones the machine happens to be set to.

Qt takes Link, Highlight and their kin from the Windows accent color, so a box
set to orange drew this app's run-title links a pale orange and its selections
an orange red -- shades in no palette any app of this family reads.
"""

from __future__ import annotations

import unittest

from PyQt6.QtGui import QPalette
from shared_ui.colors import BLUE, TEXT_PRIMARY

from gui.palette import apply_accent
from tests.gui_support import QAPP


class _FakeApp:
    """Something with a palette, so the real one is not repainted mid-suite."""

    def __init__(self, palette: QPalette):
        self._palette = palette

    def palette(self) -> QPalette:
        return QPalette(self._palette)

    def setPalette(self, palette: QPalette) -> None:
        self._palette = palette


class TestApplyAccent(unittest.TestCase):
    def _applied(self) -> QPalette:
        app = _FakeApp(QAPP.palette())
        apply_accent(app)
        return app._palette

    def test_a_link_wears_the_family_blue(self):
        self.assertEqual(
            self._applied().color(QPalette.ColorRole.Link).name(), BLUE.name())

    def test_a_visited_link_wears_the_same_blue(self):
        """These are not the web's links: a run title goes to that run's own
        lines and nowhere else, so a second color would say nothing but which
        titles had been clicked before."""
        applied = self._applied()

        self.assertEqual(applied.color(QPalette.ColorRole.LinkVisited).name(),
                         applied.color(QPalette.ColorRole.Link).name())

    def test_a_selection_wears_it_too(self):
        self.assertEqual(
            self._applied().color(QPalette.ColorRole.Highlight).name(),
            BLUE.name())

    def test_selected_text_is_the_familys_own_brightest(self):
        """Windows paired its highlight with black text, which is legible on a
        pale orange and not on this blue."""
        self.assertEqual(
            self._applied().color(QPalette.ColorRole.HighlightedText).name(),
            TEXT_PRIMARY.name())


if __name__ == "__main__":
    unittest.main()
