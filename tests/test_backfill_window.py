import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QPixmap

from backfill import vocabulary
from backfill.window import BackfillWindow


def _every_grid_phrase():
    groups = [*vocabulary.scoped_grid(), vocabulary.control_commands()]
    return {command.phrase for group in groups for command in group}



class FakeSession:
    """Stands in for BackfillSession: each scripted outcome is the note a phrase
    returns, plus the queue it leaves behind (None when the queue is untouched)."""

    def __init__(self, clips, outcomes=()):
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
        note, clips_after = self._outcomes.pop(0)
        if clips_after is not None:
            self._clips = list(clips_after)
        return note


class TestBackfillWindow(unittest.TestCase):
    def _window(self, session):
        window = BackfillWindow(session)
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        return window

    def test_the_status_line_counts_what_is_left_and_names_the_clip_on_screen(self):
        session = FakeSession([Path("a_topaz.mp4"), Path("b_topaz.mp4")])

        window = self._window(session)

        self.assertIn("2 remaining", window._status.text())
        self.assertIn("a_topaz.mp4", window._status.text())
        self.assertEqual(window._last.text(), "")

    def test_a_heard_phrase_reaches_the_session_and_advances_the_clip(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )

        window = self._window(session)
        window.on_phrase("dance")

        self.assertEqual(session.applied, ["dance"])
        self.assertIn("1 remaining", window._status.text())
        self.assertIn("b_topaz.mp4", window._status.text())

    def test_the_live_hypothesis_shows_what_the_recognizer_is_hearing(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.on_hearing("side eta")

        self.assertIn("side eta", window._hearing.text())

    def test_an_empty_hypothesis_clears_the_hearing_line(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        window.on_hearing("side")

        window.on_hearing("")

        self.assertEqual(window._hearing.text(), "")

    def test_a_landed_phrase_clears_the_stale_hearing_line(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )
        window = self._window(session)
        window.on_hearing("dance")

        window.on_phrase("dance")

        self.assertEqual(window._hearing.text(), "")

    def test_the_last_decision_names_its_own_clip_not_the_one_now_playing(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )

        window = self._window(session)
        window.on_phrase("dance")

        self.assertEqual(window._last.text(), "Last: a_topaz.mp4 → Dancing")
        self.assertNotIn("Dancing", window._status.text())

    def test_a_phrase_the_session_ignores_leaves_both_lines_alone(self):
        session = FakeSession([Path("a_topaz.mp4")], [(None, None)])

        window = self._window(session)
        status, last = window._status.text(), window._last.text()
        window.on_phrase("banana")

        self.assertEqual(window._status.text(), status)
        self.assertEqual(window._last.text(), last)

    def test_a_decision_that_leaves_the_clip_on_screen_does_not_restart_it(self):
        """An undo with nothing to undo, or a skip with only one clip left."""
        session = FakeSession([Path("a_topaz.mp4")], [("nothing to undo", None)])
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.on_phrase("undo")

        set_source.assert_not_called()
        self.assertEqual(window._last.text(), "Last: nothing to undo")

    def test_the_last_clip_leaves_a_finished_message(self):
        session = FakeSession([Path("a_topaz.mp4")], [("a_topaz.mp4 → weird", [])])

        window = self._window(session)
        window.on_phrase("weird")

        self.assertEqual(window._status.text(), "Nothing left to label.")
        self.assertEqual(window._last.text(), "Last: a_topaz.mp4 → weird")

    def test_an_empty_queue_opens_straight_to_the_finished_message(self):
        window = self._window(FakeSession([]))

        self.assertEqual(window._status.text(), "Nothing left to label.")

    def test_emptying_the_queue_releases_the_last_clip(self):
        """Otherwise the player still holds the file the background move is renaming."""
        session = FakeSession([Path("a_topaz.mp4")], [("a_topaz.mp4 → weird", [])])
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.on_phrase("weird")

        set_source.assert_called_once()
        self.assertTrue(set_source.call_args[0][0].isEmpty())

    def test_an_undo_after_the_last_clip_starts_playing_it_again(self):
        session = FakeSession([], [("undid a_topaz.mp4 → Dancing", [Path("a_topaz.mp4")])])
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.on_phrase("undo")

        set_source.assert_called_once()
        self.assertIn("a_topaz.mp4", set_source.call_args[0][0].toLocalFile())
        self.assertIn("1 remaining", window._status.text())
        self.assertEqual(window._last.text(), "Last: undid a_topaz.mp4 → Dancing")

    def test_a_clickable_tile_exists_for_every_command_in_the_grid(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        self.assertEqual(set(window._command_buttons), _every_grid_phrase())

    def test_a_tile_is_labelled_with_the_action_it_records(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        self.assertEqual(window._command_buttons["side beta"].text(), "Side Beta")

    def test_clicking_a_tile_applies_its_phrase_through_the_session(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → skipped", None)],
        )
        window = self._window(session)

        window._command_buttons["skip"].click()

        self.assertEqual(session.applied, ["skip"])

    def _png(self, tmp):
        png = Path(tmp) / "frame.png"
        pixmap = QPixmap(20, 20)
        pixmap.fill()
        pixmap.save(str(png))
        return png

    def test_a_ready_thumbnail_appears_on_the_tile_for_its_action(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        with tempfile.TemporaryDirectory() as tmp:
            window.set_thumbnail("Side Beta", str(self._png(tmp)))

            self.assertFalse(window._tiles_by_action["side beta"].icon().isNull())

    def test_an_example_stored_under_older_casing_still_lights_its_tile(self):
        """Library clips tagged "Pov ..." must reach the "POV ..." tile."""
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        with tempfile.TemporaryDirectory() as tmp:
            window.set_thumbnail("Pov Beta", str(self._png(tmp)))

            self.assertFalse(window._tiles_by_action["pov beta"].icon().isNull())

    def test_a_thumbnail_for_an_action_with_no_tile_is_ignored(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.set_thumbnail("Not An Act", "whatever.png")  # must not raise

    def test_an_empty_thumbnail_path_leaves_the_tile_iconless(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.set_thumbnail("Side Beta", "")

        self.assertTrue(window._tiles_by_action["side beta"].icon().isNull())

    def test_thumbnails_passed_at_construction_land_on_their_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = BackfillWindow(
                FakeSession([Path("a_topaz.mp4")]), thumbnails={"Side Beta": str(self._png(tmp))}
            )
            self.addCleanup(window.close)
            self.addCleanup(window.deleteLater)

            self.assertFalse(window._tiles_by_action["side beta"].icon().isNull())

    def test_closing_releases_the_clip_the_player_holds(self):
        session = FakeSession([Path("a_topaz.mp4")])
        # Through the helper, for its cleanups: closing the window inside the
        # patch below is what this test is about, but the window itself still has
        # to be deleted afterwards. Left to Python's collector it went at some
        # unpredictable later moment, and the media player's queued callback
        # arrived at a half-collected slot -- "TypeError: 'NoneType' object is
        # not callable" out of the Qt event loop, in five teardowns out of ten.
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.close()

        set_source.assert_called_once()
        self.assertTrue(set_source.call_args[0][0].isEmpty())


if __name__ == "__main__":
    unittest.main()
