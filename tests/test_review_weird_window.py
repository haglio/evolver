from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMessageBox

from review_weird.window import ReviewWeirdWindow
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir


class _ReviewingALibrary(unittest.TestCase):
    def setUp(self):
        workspace = workspace_temp_dir()
        self.lib = LaneLibrary(workspace.__enter__())
        self.addCleanup(workspace.__exit__, None, None, None)
        configured = self.lib.config()
        configured.__enter__()
        self.addCleanup(configured.__exit__, None, None, None)

    def _window(self) -> ReviewWeirdWindow:
        window = ReviewWeirdWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        return window

    def _rows(self, window: ReviewWeirdWindow) -> list[tuple[str, str]]:
        return [(window.videos.topLevelItem(row).text(0), window.videos.topLevelItem(row).text(1))
                for row in range(window.videos.topLevelItemCount())]


class TestWhatTheWindowLists(_ReviewingALibrary):
    def test_every_video_marked_weird_is_listed_with_the_folder_it_goes_back_to(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene one.mp4")
        touch_video(self.lib.weird / "scene one_topaz.mp4")
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_1_topaz.mp4")

        window = self._window()

        self.assertEqual(window.heading.text(), "2 videos marked weird")
        self.assertEqual(self._rows(window), [
            ("scene one_topaz.mp4",
             r"videos\2D\AI\2_outbox\upscaled_by_orientation\portrait\example-source"),
            ("loop_1_topaz.mp4", r"genau\clips\2D\AI"),
        ])

    def test_the_heading_counts_one_video_as_one(self):
        touch_video(self.lib.genau_weird / "loop_2_topaz.mp4")

        self.assertEqual(self._window().heading.text(), "1 video marked weird")

    def test_with_nothing_marked_the_heading_says_so(self):
        self.assertEqual(self._window().heading.text(), "Nothing is marked weird")

    def test_a_video_nothing_says_the_place_of_reads_as_cant_tell_and_says_why(self):
        touch_video(self.lib.weird / "scene two.mp4")

        window = self._window()

        self.assertEqual(self._rows(window), [("scene two.mp4", "can't tell")])
        self.assertEqual(window.videos.topLevelItem(0).toolTip(1),
                         "Nothing says which folder it was marked weird in, so it can't be put back")

    def test_each_row_says_in_full_where_the_video_is_and_where_it_goes(self):
        marked = touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_14_topaz.mp4")

        row = self._window().videos.topLevelItem(0)

        self.assertEqual((row.toolTip(0), row.toolTip(1)),
                         (str(marked), str(self.lib.genau_clips / "2D" / "AI" / "loop_14_topaz.mp4")))


class TestWatchingOne(_ReviewingALibrary):
    def test_the_first_video_plays_and_clicking_another_plays_that_one(self):
        first = touch_video(self.lib.genau_weird / "loop_3_topaz.mp4")
        second = touch_video(self.lib.genau_weird / "loop_4_topaz.mp4")
        window = self._window()
        playing_first = _playing(window)

        window.videos.setCurrentItem(window.videos.topLevelItem(1))

        self.assertEqual((playing_first, _playing(window)), (first, second))

    def test_what_the_player_reads_out_of_a_video_is_kept_out_of_every_log(self):
        with patch("review_weird.window.silence_the_ffmpeg_format_dump") as silenced:
            self._window()

        silenced.assert_called_once_with()


class TestPuttingBack(_ReviewingALibrary):
    def test_the_selected_video_goes_back_and_the_next_one_plays(self):
        touch_video(self.lib.genau_weird / "loop_5_topaz.mp4")
        after = touch_video(self.lib.genau_weird / "loop_6_topaz.mp4")
        window = self._window()

        window.put_back_button.click()

        self.assertTrue((self.lib.genau_clips / "loop_5_topaz.mp4").is_file())
        self.assertEqual(self._rows(window), [("loop_6_topaz.mp4", "genau\\clips")])
        self.assertEqual(_playing(window), after)

    def test_one_that_cannot_go_back_is_named_and_the_rest_still_go(self):
        touch_video(self.lib.genau_weird / "loop_11_topaz.mp4")
        touch_video(self.lib.genau_weird / "loop_12_topaz.mp4")
        window = self._window()
        window.videos.selectAll()
        touch_video(self.lib.genau_clips / "loop_11_topaz.mp4")

        with patch("review_weird.window.QMessageBox.warning") as warned:
            window.put_back_button.click()

        self.assertIn("loop_11_topaz.mp4", warned.call_args.args[2])
        self.assertTrue((self.lib.genau_clips / "loop_12_topaz.mp4").is_file())
        self.assertEqual([row[0] for row in self._rows(window)], ["loop_11_topaz.mp4"])


class TestWhatCanBeDone(_ReviewingALibrary):
    def test_with_nothing_marked_neither_verdict_can_be_given(self):
        window = self._window()

        self.assertEqual((window.put_back_button.isEnabled(), window.delete_button.isEnabled()),
                         (False, False))

    def test_a_video_nothing_says_the_place_of_can_be_deleted_but_not_put_back(self):
        touch_video(self.lib.weird / "scene three.mp4")
        touch_video(self.lib.genau_weird / "loop_10_topaz.mp4")
        window = self._window()
        window.videos.selectAll()

        self.assertEqual((window.put_back_button.isEnabled(), window.delete_button.isEnabled()),
                         (False, True))


class TestDeletingForGood(_ReviewingALibrary):
    def test_it_asks_first_and_deletes_only_on_yes(self):
        marked = touch_video(self.lib.genau_weird / "loop_7_topaz.mp4")
        window = self._window()

        with _answering(QMessageBox.StandardButton.No) as asked:
            window.delete_button.click()
        kept = marked.exists()
        with _answering(QMessageBox.StandardButton.Yes):
            window.delete_button.click()

        self.assertEqual(asked.call_args.args[2], "Delete loop_7_topaz.mp4 for good? This can't be undone.")
        self.assertEqual((kept, marked.exists()), (True, False))
        self.assertEqual(window.heading.text(), "Nothing is marked weird")

    def test_several_selected_are_asked_about_once_and_all_deleted(self):
        marked = [touch_video(self.lib.genau_weird / f"loop_{number}_topaz.mp4") for number in (8, 9)]
        window = self._window()
        window.videos.selectAll()

        with _answering(QMessageBox.StandardButton.Yes) as asked:
            window.delete_button.click()

        asked.assert_called_once()
        self.assertEqual(asked.call_args.args[2], "Delete these 2 videos for good? This can't be undone.")
        self.assertEqual([video for video in marked if video.exists()], [])

    def test_the_delete_key_asks_the_same_question(self):
        marked = touch_video(self.lib.genau_weird / "loop_13_topaz.mp4")
        window = self._window()
        [delete_key] = [shortcut for shortcut in window.findChildren(QShortcut)
                        if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Delete)]

        with _answering(QMessageBox.StandardButton.Yes) as asked:
            delete_key.activated.emit()

        asked.assert_called_once()
        self.assertFalse(marked.exists())

    def test_the_delete_key_with_nothing_marked_asks_nothing(self):
        window = self._window()
        [delete_key] = [shortcut for shortcut in window.findChildren(QShortcut)
                        if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Delete)]

        with _answering(QMessageBox.StandardButton.Yes) as asked:
            delete_key.activated.emit()

        asked.assert_not_called()


def _answering(button):
    return patch("review_weird.window.QMessageBox.question", return_value=button)


def _playing(window: ReviewWeirdWindow) -> Path:
    return Path(window.player.source().toLocalFile())


if __name__ == "__main__":
    unittest.main()
