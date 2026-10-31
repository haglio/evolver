from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QKeySequence, QShortcut
from shared_ui.colors import BLUE

from review_weird.window import ReviewWeirdWindow
from tests.gui_support import QAPP, row_ground
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
    def test_every_video_marked_weird_is_listed_with_the_folder_it_restores_to(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene one.mp4")
        touch_video(self.lib.weird / "scene one_topaz.mp4")
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_1_topaz.mp4")

        window = self._window()

        assert window.heading.text() == "2 videos marked weird"
        assert self._rows(window) == [("scene one_topaz.mp4", r"videos\2D\AI\2_outbox\upscaled_by_orientation\portrait\example-source"), ("loop_1_topaz.mp4", r"videos\genau\flicks\2D\AI")]

    def test_the_heading_counts_one_video_as_one(self):
        touch_video(self.lib.genau_weird / "loop_2_topaz.mp4")

        assert self._window().heading.text() == "1 video marked weird"

    def test_with_nothing_marked_the_heading_says_so(self):
        assert self._window().heading.text() == "Nothing is marked weird"

    def test_a_video_marked_weird_while_the_window_is_open_shows_up_in_it(self):
        touch_video(self.lib.genau_weird / "loop_15_topaz.mp4")
        window = self._window()
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_16_topaz.mp4")

        window.watch.timeout.emit()

        assert [row[0] for row in self._rows(window)] == ["loop_15_topaz.mp4", "loop_16_topaz.mp4"]
        assert window.heading.text() == "2 videos marked weird"

    def test_the_video_playing_plays_on_while_another_arrives(self):
        touch_video(self.lib.genau_weird / "loop_17_topaz.mp4")
        playing = touch_video(self.lib.genau_weird / "loop_18_topaz.mp4")
        window = self._window()
        window.videos.setCurrentItem(window.videos.topLevelItem(1))
        touch_video(self.lib.genau_weird / "loop_19_topaz.mp4")

        with patch.object(window.preview.player, "setSource", wraps=window.preview.player.setSource) as switched:
            window.watch.timeout.emit()

        switched.assert_not_called()
        assert _playing(window) == playing
        assert window.videos.currentItem().text(0) == "loop_18_topaz.mp4"

    def test_the_videos_picked_stay_picked_while_another_arrives(self):
        for number in (20, 21, 22):
            touch_video(self.lib.genau_weird / f"loop_{number}_topaz.mp4")
        window = self._window()
        window.videos.selectAll()
        touch_video(self.lib.genau_weird / "loop_23_topaz.mp4")

        window.watch.timeout.emit()

        assert sorted(item.text(0) for item in window.videos.selectedItems()) == ["loop_20_topaz.mp4", "loop_21_topaz.mp4", "loop_22_topaz.mp4"]

    def test_the_folders_are_looked_at_again_every_couple_of_seconds_while_it_is_open(self):
        window = self._window()

        window.show()
        while_open = (window.watch.isActive(), window.watch.interval())
        window.hide()

        assert (while_open, window.watch.isActive()) == ((True, 2000), False)

    def test_a_video_nothing_says_the_place_of_reads_as_cant_tell_and_says_why(self):
        touch_video(self.lib.weird / "scene two.mp4")

        window = self._window()

        assert self._rows(window) == [("scene two.mp4", "can't tell")]
        assert window.videos.topLevelItem(0).toolTip(1) == "Nothing says which folder it was marked weird in, so it can't be restored"

    def test_each_row_says_in_full_where_the_video_is_and_where_it_goes(self):
        marked = touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_14_topaz.mp4")

        row = self._window().videos.topLevelItem(0)

        assert (row.toolTip(0), row.toolTip(1)) == (str(marked), str(self.lib.genau_flicks / "2D" / "AI" / "loop_14_topaz.mp4"))


class TestWatchingOne(_ReviewingALibrary):
    def test_the_first_video_plays_and_clicking_another_plays_that_one(self):
        first = touch_video(self.lib.genau_weird / "loop_3_topaz.mp4")
        second = touch_video(self.lib.genau_weird / "loop_4_topaz.mp4")
        window = self._window()
        playing_first = _playing(window)

        window.videos.setCurrentItem(window.videos.topLevelItem(1))

        assert (playing_first, _playing(window)) == (first, second)

    def test_a_video_plays_with_no_sound_output_at_all(self):
        touch_video(self.lib.genau_weird / "loop_5_topaz.mp4")

        window = self._window()

        assert window.preview.player.audioOutput() is None

    def test_what_the_player_reads_out_of_a_video_is_kept_out_of_every_log(self):
        with patch("util.looping_preview.silence_the_ffmpeg_format_dump") as silenced:
            self._window()

        silenced.assert_called_once_with()


def _row_colors(view, row: int) -> set[str]:
    """Every color *row* is painted in, across all its cells."""
    QAPP.processEvents()
    first = view.visualRect(view.model().index(row, 0))
    last = view.visualRect(view.model().index(row, view.model().columnCount() - 1))
    painted = view.viewport().grab().toImage()
    return {painted.pixelColor(x, y).name()
            for y in range(first.top(), first.top() + first.height())
            for x in range(first.left(), last.left() + last.width())}


class TestPickedRows(_ReviewingALibrary):
    def test_every_picked_row_wears_the_familys_blue(self):
        for number in (24, 25, 26):
            touch_video(self.lib.genau_weird / f"loop_{number}_topaz.mp4")
        window = self._window()
        window.show()
        window.videos.topLevelItem(0).setSelected(True)
        window.videos.topLevelItem(2).setSelected(True)

        grounds = [row_ground(window.videos, row) for row in range(3)]

        assert grounds[0] == BLUE.name()
        assert grounds[2] == BLUE.name()
        assert grounds[1] != BLUE.name()

    def test_the_row_the_keyboard_is_on_wears_no_frame_round_its_blue(self):
        touch_video(self.lib.genau_weird / "loop_27_topaz.mp4")
        window = self._window()
        window.show()
        window.activateWindow()
        QAPP.processEvents()
        window.videos.setFocus()
        window.videos.setCurrentItem(window.videos.topLevelItem(0))
        for column in range(window.videos.columnCount()):
            window.videos.topLevelItem(0).setText(column, "")
        QAPP.processEvents()

        assert window.videos.hasFocus()
        assert _row_colors(window.videos, 0) == {BLUE.name()}


class TestRestoring(_ReviewingALibrary):
    def test_the_selected_video_is_restored_and_the_next_one_plays(self):
        touch_video(self.lib.genau_weird / "loop_5_topaz.mp4")
        after = touch_video(self.lib.genau_weird / "loop_6_topaz.mp4")
        window = self._window()

        window.restore_button.click()

        assert (self.lib.genau_flicks / "loop_5_topaz.mp4").is_file()
        assert self._rows(window) == [("loop_6_topaz.mp4", "videos\\genau\\flicks")]
        assert _playing(window) == after

    def test_one_that_cannot_be_restored_is_named_and_the_rest_still_are(self):
        touch_video(self.lib.genau_weird / "loop_11_topaz.mp4")
        touch_video(self.lib.genau_weird / "loop_12_topaz.mp4")
        window = self._window()
        window.videos.selectAll()
        touch_video(self.lib.genau_flicks / "loop_11_topaz.mp4")

        with patch("review_weird.window.QMessageBox.warning") as warned:
            window.restore_button.click()

        assert "loop_11_topaz.mp4" in warned.call_args.args[2]
        assert (self.lib.genau_flicks / "loop_12_topaz.mp4").is_file()
        assert [row[0] for row in self._rows(window)] == ["loop_11_topaz.mp4"]


class TestWhatCanBeDone(_ReviewingALibrary):
    def test_with_nothing_marked_neither_verdict_can_be_given(self):
        window = self._window()

        assert (window.restore_button.isEnabled(), window.delete_button.isEnabled()) == (False, False)

    def test_a_video_nothing_says_the_place_of_can_be_deleted_but_not_restored(self):
        touch_video(self.lib.weird / "scene three.mp4")
        touch_video(self.lib.genau_weird / "loop_10_topaz.mp4")
        window = self._window()
        window.videos.selectAll()

        assert (window.restore_button.isEnabled(), window.delete_button.isEnabled()) == (False, True)


class TestDeletingPermanently(_ReviewingALibrary):
    def test_it_deletes_at_once_without_asking(self):
        marked = touch_video(self.lib.genau_weird / "loop_7_topaz.mp4")
        window = self._window()

        with _no_question_asked() as asked:
            window.delete_button.click()

        asked.assert_not_called()
        assert not marked.exists()
        assert window.heading.text() == "Nothing is marked weird"

    def test_several_selected_all_go_at_once(self):
        marked = [touch_video(self.lib.genau_weird / f"loop_{number}_topaz.mp4") for number in (8, 9)]
        window = self._window()
        window.videos.selectAll()

        window.delete_button.click()

        assert [video for video in marked if video.exists()] == []

    def test_the_delete_key_deletes_too(self):
        marked = touch_video(self.lib.genau_weird / "loop_13_topaz.mp4")
        window = self._window()

        _delete_key(window).activated.emit()

        assert not marked.exists()

    def test_the_delete_key_with_nothing_marked_does_nothing(self):
        window = self._window()

        _delete_key(window).activated.emit()

        assert window.heading.text() == "Nothing is marked weird"


def _no_question_asked():
    return patch("review_weird.window.QMessageBox.question")


def _delete_key(window: ReviewWeirdWindow) -> QShortcut:
    [key] = [shortcut for shortcut in window.findChildren(QShortcut)
             if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Delete)]
    return key


def _playing(window: ReviewWeirdWindow) -> Path:
    return Path(window.preview.player.source().toLocalFile())


if __name__ == "__main__":
    unittest.main()
