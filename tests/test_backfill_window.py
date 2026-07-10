import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from backfill.window import BackfillWindow

_app = QApplication.instance() or QApplication([])


class FakeSession:
    """Stands in for BackfillSession: records what was applied, scripts the queue."""

    def __init__(self, clips, outcomes):
        self._clips = list(clips)
        self._outcomes = list(outcomes)
        self.applied = []

    @property
    def remaining(self):
        return len(self._clips)

    @property
    def current(self):
        return self._clips[0] if self._clips else None

    def apply(self, phrase):
        self.applied.append(phrase)
        outcome = self._outcomes.pop(0)
        if outcome is not None:
            self._clips.pop(0)
        return outcome


class TestBackfillWindow(unittest.TestCase):
    def _window(self, session):
        window = BackfillWindow(session)
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        return window

    def test_the_status_line_counts_what_is_left_and_names_the_clip(self):
        session = FakeSession([Path("a_topaz.mp4"), Path("b_topaz.mp4")], [])

        window = self._window(session)

        self.assertIn("2 remaining", window._status.text())
        self.assertIn("a_topaz.mp4", window._status.text())

    def test_a_heard_phrase_reaches_the_session_and_advances_the_clip(self):
        session = FakeSession([Path("a_topaz.mp4"), Path("b_topaz.mp4")], ["Dancing"])

        window = self._window(session)
        window.on_phrase("dance")

        self.assertEqual(session.applied, ["dance"])
        self.assertIn("1 remaining", window._status.text())
        self.assertIn("Dancing", window._status.text())
        self.assertIn("b_topaz.mp4", window._status.text())

    def test_a_phrase_the_session_ignores_leaves_the_status_line_alone(self):
        session = FakeSession([Path("a_topaz.mp4")], [None])

        window = self._window(session)
        before = window._status.text()
        window.on_phrase("banana")

        self.assertEqual(window._status.text(), before)

    def test_the_last_clip_leaves_a_finished_message(self):
        session = FakeSession([Path("a_topaz.mp4")], ["Weird"])

        window = self._window(session)
        window.on_phrase("weird")

        self.assertEqual(window._status.text(), "Nothing left to label.")

    def test_emptying_the_queue_releases_the_last_clip(self):
        """Otherwise the player still holds the file the background move is renaming."""
        session = FakeSession([Path("a_topaz.mp4")], ["Weird"])
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.on_phrase("weird")

        set_source.assert_called_once()
        self.assertTrue(set_source.call_args[0][0].isEmpty())

    def test_an_empty_queue_opens_straight_to_the_finished_message(self):
        window = self._window(FakeSession([], []))

        self.assertEqual(window._status.text(), "Nothing left to label.")

    def test_closing_releases_the_clip_the_player_holds(self):
        session = FakeSession([Path("a_topaz.mp4")], [])
        window = BackfillWindow(session)

        with patch.object(window._player, "setSource") as set_source:
            window.close()

        set_source.assert_called_once()
        self.assertTrue(set_source.call_args[0][0].isEmpty())


if __name__ == "__main__":
    unittest.main()
