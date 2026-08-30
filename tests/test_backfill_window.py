import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QToolButton

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

        self.assertIn("2 remaining", window.status_text())
        self.assertIn("a_topaz.mp4", window.status_text())
        self.assertEqual(window.last_text(), "")

    def test_a_heard_phrase_reaches_the_session_and_advances_the_clip(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )

        window = self._window(session)
        window.on_phrase("dance")

        self.assertEqual(session.applied, ["dance"])
        self.assertIn("1 remaining", window.status_text())
        self.assertIn("b_topaz.mp4", window.status_text())

    def test_the_live_hypothesis_shows_what_the_recognizer_is_hearing(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.on_hearing("side eta")

        self.assertIn("side eta", window.hearing_text())

    def test_an_empty_hypothesis_clears_the_hearing_line(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        window.on_hearing("side")

        window.on_hearing("")

        self.assertEqual(window.hearing_text(), "")

    def test_a_landed_phrase_clears_the_stale_hearing_line(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )
        window = self._window(session)
        window.on_hearing("dance")

        window.on_phrase("dance")

        self.assertEqual(window.hearing_text(), "")

    def test_the_last_decision_names_its_own_clip_not_the_one_now_playing(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → Dancing", [Path("b_topaz.mp4")])],
        )

        window = self._window(session)
        window.on_phrase("dance")

        self.assertEqual(window.last_text(), "Last: a_topaz.mp4 → Dancing")
        self.assertNotIn("Dancing", window.status_text())

    def test_a_phrase_the_session_ignores_leaves_both_lines_alone(self):
        session = FakeSession([Path("a_topaz.mp4")], [(None, None)])

        window = self._window(session)
        status, last = window.status_text(), window.last_text()
        window.on_phrase("banana")

        self.assertEqual(window.status_text(), status)
        self.assertEqual(window.last_text(), last)

    def test_a_decision_that_leaves_the_clip_on_screen_does_not_restart_it(self):
        """An undo with nothing to undo, or a skip with only one clip left."""
        session = FakeSession([Path("a_topaz.mp4")], [("nothing to undo", None)])
        window = self._window(session)

        with patch.object(window._player, "setSource") as set_source:
            window.on_phrase("undo")

        set_source.assert_not_called()
        self.assertEqual(window.last_text(), "Last: nothing to undo")

    def test_the_last_clip_leaves_a_finished_message(self):
        session = FakeSession([Path("a_topaz.mp4")], [("a_topaz.mp4 → weird", [])])

        window = self._window(session)
        window.on_phrase("weird")

        self.assertEqual(window.status_text(), "Nothing left to label.")
        self.assertEqual(window.last_text(), "Last: a_topaz.mp4 → weird")

    def test_an_empty_queue_opens_straight_to_the_finished_message(self):
        window = self._window(FakeSession([]))

        self.assertEqual(window.status_text(), "Nothing left to label.")

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
        self.assertIn("1 remaining", window.status_text())
        self.assertEqual(window.last_text(), "Last: undid a_topaz.mp4 → Dancing")

    def test_the_window_is_built_from_a_session_and_its_thumbnails(self):
        """It is the top-level window of its own process — nothing owns it, so
        there is no parent to take."""
        self.assertEqual(
            list(inspect.signature(BackfillWindow.__init__).parameters)[1:],
            ["session", "thumbnails"],
        )

    def test_a_clickable_tile_exists_for_every_command_in_the_grid(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        missing = {phrase for phrase in _every_grid_phrase() if window.tile_for(phrase) is None}
        self.assertEqual(missing, set())

    def test_a_tile_is_labelled_with_the_action_it_records(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        self.assertEqual(window.tile_for("side beta").text(), "Side Beta")

    def test_clicking_a_tile_applies_its_phrase_through_the_session(self):
        session = FakeSession(
            [Path("a_topaz.mp4"), Path("b_topaz.mp4")],
            [("a_topaz.mp4 → skipped", None)],
        )
        window = self._window(session)

        window.tile_for("skip").click()

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

            self.assertFalse(window.tile_for("side beta").icon().isNull())

    def test_an_example_stored_under_older_casing_still_lights_its_tile(self):
        """Library clips tagged "Pov ..." must reach the "POV ..." tile."""
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        with tempfile.TemporaryDirectory() as tmp:
            window.set_thumbnail("Pov Beta", str(self._png(tmp)))

            self.assertFalse(window.tile_for("pov beta").icon().isNull())

    def test_a_thumbnail_for_an_action_with_no_tile_is_ignored(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.set_thumbnail("Not An Act", "whatever.png")  # must not raise

        # ...and must not have decorated some other act's tile with it either
        self.assertTrue(
            all(tile.icon().isNull() for tile in window.findChildren(QToolButton))
        )

    def test_an_empty_thumbnail_path_leaves_the_tile_iconless(self):
        window = self._window(FakeSession([Path("a_topaz.mp4")]))

        window.set_thumbnail("Side Beta", "")

        self.assertTrue(window.tile_for("side beta").icon().isNull())

    def test_thumbnails_passed_at_construction_land_on_their_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = BackfillWindow(
                FakeSession([Path("a_topaz.mp4")]), thumbnails={"Side Beta": str(self._png(tmp))}
            )
            self.addCleanup(window.close)
            self.addCleanup(window.deleteLater)

            self.assertFalse(window.tile_for("side beta").icon().isNull())

    def test_the_clips_own_soundtrack_is_muted(self):
        """The microphone is open the whole session; a clip's audio would be
        one more thing for the recognizer to mishear. Unmuting survived the
        whole suite before (audit probe 23)."""
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        self.assertTrue(window._audio.isMuted())

    def test_the_clip_loops_until_a_decision_lands(self):
        from PyQt6.QtMultimedia import QMediaPlayer

        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        self.assertEqual(window._player.loops(), QMediaPlayer.Loops.Infinite)

    def test_releasing_the_last_clip_also_stops_the_player(self):
        """Dropping the source without stop() left playback tearing at a file
        the background discard is renaming (audit probe 25 deleted the stop
        with the suite green)."""
        session = FakeSession([Path("a_topaz.mp4")], [("a_topaz.mp4 → weird", [])])
        window = self._window(session)

        with patch.object(window._player, "stop") as stop, \
             patch.object(window._player, "setSource"):
            window.on_phrase("weird")

        stop.assert_called_once()

    def test_escape_closes_the_window(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence, QShortcut

        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        escapes = [
            s for s in window.findChildren(QShortcut)
            if s.key() == QKeySequence(Qt.Key.Key_Escape)
        ]
        self.assertEqual(len(escapes), 1)

        window.show()
        self.assertTrue(window.isVisible())
        escapes[0].activated.emit()
        self.assertFalse(window.isVisible())

    def test_no_tile_ever_takes_keyboard_focus(self):
        """The space bar must not re-fire the last clicked tile, and Esc must
        keep closing the window rather than being swallowed by a button."""
        from PyQt6.QtCore import Qt

        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        tiles = window.findChildren(QToolButton)
        self.assertTrue(tiles)
        for tile in tiles:
            self.assertEqual(tile.focusPolicy(), Qt.FocusPolicy.NoFocus)

    def test_a_portrait_frame_lands_unsquished_on_a_square_icon(self):
        """The fix for portrait/landscape frames coming out squished to square
        on native Windows: the icon pixmap is already the icon size, scaled to
        fit with its ratio kept and centred on transparent margins."""
        window = self._window(FakeSession([Path("a_topaz.mp4")]))
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "portrait.png"
            pixmap = QPixmap(20, 40)
            pixmap.fill()  # opaque white
            pixmap.save(str(png))
            window.set_thumbnail("Side Beta", str(png))

            icon = window.tile_for("side beta").icon()
            rendered = icon.pixmap(96, 96)
            self.assertEqual((rendered.width(), rendered.height()), (96, 96))
            image = rendered.toImage()
            # a 20x40 frame fits 96x96 as 48x96: opaque centre, transparent
            # margins on the short axis
            self.assertEqual(image.pixelColor(48, 48).alpha(), 255)
            self.assertEqual(image.pixelColor(5, 48).alpha(), 0)
            self.assertEqual(image.pixelColor(90, 48).alpha(), 0)

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
