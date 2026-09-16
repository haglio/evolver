"""The upscale queue window: what it shows, and what it says the user did.

Every video here is invented, and so is every title.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QPoint, Qt

from gui import queue_window
from gui.queue_window import UpscaleQueueWindow, running_time
from util.upscale_lineup import (
    ASKED_FOR,
    FINISHING,
    NEXT,
    PAUSED,
    STARTING,
    UPSCALING,
    Entry,
    Head,
    Lineup,
)


def entry(video, name=None, seconds=754.0, pinned=False):
    return Entry(video=video, name=name or video, seconds=seconds, pinned=pinned)


def lineup(head=None, *entries):
    return Lineup(rows=tuple(entries), head=head or Head(NEXT))


@pytest.fixture
def window():
    made = UpscaleQueueWindow()
    made.resize(700, 400)
    yield made
    made.deleteLater()


def icon_of(window, row: int):
    """What the first column of *row* draws, as pixels to compare."""
    return window._tree.topLevelItem(row).icon(0).pixmap(16, 16).toImage()


def arrow(filled: bool):
    return queue_window._arrow(Head(ASKED_FOR if filled else NEXT)).pixmap(16, 16).toImage()


def blank_arrow():
    return queue_window._arrow(None).pixmap(16, 16).toImage()


def draggable(window, row: int) -> bool:
    return bool(window._tree.topLevelItem(row).flags() & Qt.ItemFlag.ItemIsDragEnabled)


def click(window, row: int, column: int = 0) -> None:
    window._tree.itemClicked.emit(window._tree.topLevelItem(row), column)


class TestWhatItShows:
    def test_every_video_is_a_numbered_row_in_order(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", "Jane Doe - Alpha Study 3"),
                                  entry("larkin/0 unsorted/b.mp4", "b", seconds=None)))

        assert window._tree.videos() == ["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/b.mp4"]
        assert window._tree.topLevelItem(0).text(1) == "Jane Doe - Alpha Study 3"
        assert window._tree.topLevelItem(0).text(3) == "12:34"
        assert window._tree.topLevelItem(0).text(0) == "1"
        assert window._tree.topLevelItem(1).text(0) == "2"
        assert window._tree.topLevelItem(1).text(3) == ""

    def test_the_first_row_says_what_is_happening_to_its_video(self, window):
        window.show_lineup(lineup(Head(UPSCALING, percent=41),
                                  entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))

        assert window._tree.topLevelItem(0).text(2) == "Upscaling — 41% done"
        assert window._tree.topLevelItem(1).text(2) == ""

    @pytest.mark.parametrize(("head", "words"), [
        (Head(NEXT), "Next, once you're away from the computer"),
        (Head(PAUSED, percent=41), "Paused while you're at the computer — 41% done"),
        (Head(ASKED_FOR, percent=2), "Upscaling at your request — 2% done"),
        (Head(STARTING, held_back="low_ram"),
         "Starting at your request — waiting for memory to free up"),
        (Head(FINISHING), "Done upscaling; Evolver's next run replaces the original with it"),
    ])
    def test_each_state_reads_as_words_rather_than_the_stages_own(self, window, head, words):
        window.show_lineup(lineup(head, entry("larkin/0 unsorted/a.mp4")))

        assert window._tree.topLevelItem(0).text(2) == words

    def test_the_heading_counts_the_videos_and_their_hours(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", seconds=3600.0),
                                  entry("larkin/0 unsorted/b.mp4", seconds=1800.0)))

        assert window._heading.text() == "2 videos, 1.5 hours of footage"

    def test_an_empty_queue_says_so(self, window):
        window.show_lineup(Lineup(rows=(), head=None))

        assert window._heading.text() == "Nothing is waiting to be upscaled"
        assert window._tree.videos() == []


class TestTheArrow:
    """Only the first row has one: you cannot ask for two videos at once."""

    def test_it_is_filled_while_the_first_row_runs_whoever_is_here(self, window):
        window.show_lineup(lineup(Head(ASKED_FOR, percent=2),
                                  entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))

        assert icon_of(window, 0) == arrow(filled=True)
        assert icon_of(window, 1) == blank_arrow()

    def test_it_is_hollow_while_the_first_row_waits_for_you_to_leave(self, window):
        window.show_lineup(lineup(Head(PAUSED, percent=41), entry("larkin/0 unsorted/a.mp4")))

        assert icon_of(window, 0) == arrow(filled=False)

    def test_a_video_whose_encode_has_ended_has_none_to_click(self, window):
        window.show_lineup(lineup(Head(FINISHING), entry("larkin/0 unsorted/a.mp4")))

        assert icon_of(window, 0) == blank_arrow()

    def test_clicking_a_hollow_one_asks_for_that_video_now(self, window):
        window.show_lineup(lineup(Head(NEXT), entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))
        asked, withdrawn = [], []
        window.now_requested.connect(asked.append)
        window.now_withdrawn.connect(lambda: withdrawn.append(True))

        click(window, 0)

        assert asked == ["larkin/0 unsorted/a.mp4"]
        assert withdrawn == []
        assert icon_of(window, 0) == arrow(filled=True)

    def test_clicking_a_filled_one_hands_the_video_back_to_your_presence(self, window):
        window.show_lineup(lineup(Head(ASKED_FOR, percent=2), entry("larkin/0 unsorted/a.mp4")))
        asked, withdrawn = [], []
        window.now_requested.connect(asked.append)
        window.now_withdrawn.connect(lambda: withdrawn.append(True))

        click(window, 0)

        assert withdrawn == [True]
        assert asked == []
        assert icon_of(window, 0) == arrow(filled=False)
        assert window._tree.topLevelItem(0).text(2) == "Upscaling — 2% done"

    def test_the_rest_of_the_row_is_not_the_arrow(self, window):
        window.show_lineup(lineup(Head(NEXT), entry("larkin/0 unsorted/a.mp4")))
        asked = []
        window.now_requested.connect(asked.append)

        click(window, 0, column=1)

        assert asked == []

    def test_a_second_row_is_not_the_arrow_either(self, window):
        window.show_lineup(lineup(Head(NEXT), entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))
        asked = []
        window.now_requested.connect(asked.append)

        click(window, 1)

        assert asked == []


class TestWhatItSaysTheUserDid:
    def _arrangements(self, window):
        seen = []
        window.arranged.connect(seen.append)
        return seen

    def test_a_video_dragged_to_the_top_goes_first_and_waits_like_any_other(self, window):
        """Putting a video first is not asking for it now: the arrow stays
        off until it is clicked."""
        window.show_lineup(lineup(Head(UPSCALING, percent=41),
                                  *(entry(f"larkin/0 unsorted/{name}.mp4") for name in "abc")))
        asked, first = [], []
        window.now_requested.connect(asked.append)
        window.placed_first.connect(first.append)
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/c.mp4", 0)

        assert first == ["larkin/0 unsorted/c.mp4"]
        assert asked == []
        assert seen == []
        assert window._tree.videos() == ["larkin/0 unsorted/c.mp4", "larkin/0 unsorted/a.mp4",
                                         "larkin/0 unsorted/b.mp4"]
        assert window._tree.topLevelItem(0).text(2) == "Next, once you're away from the computer"
        assert window._tree.topLevelItem(1).text(2) == ""
        assert icon_of(window, 0) == arrow(filled=False)

    def test_a_video_dragged_lower_down_keeps_everything_above_it_where_it_is(self, window):
        """Its place is only its place if the videos it was put after stay
        where they are."""
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abcd")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/d.mp4", 2)

        assert seen == [["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/b.mp4",
                         "larkin/0 unsorted/d.mp4"]]
        assert window._tree.topLevelItem(2).text(0) == "3"

    def test_a_video_pushed_below_a_placed_one_keeps_that_place_in_the_order(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", pinned=True),
                                  entry("larkin/0 unsorted/b.mp4"),
                                  entry("larkin/0 unsorted/c.mp4")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/c.mp4", 1)

        assert seen == [["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/c.mp4"]]

    def test_a_row_dropped_back_where_it_was_changes_nothing(self, window):
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abc")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/b.mp4", 1)
        window._tree.move_video("larkin/0 unsorted/b.mp4", 2)

        assert seen == []

    def test_the_video_being_upscaled_cannot_be_dragged_off_the_top(self, window):
        window.show_lineup(lineup(Head(UPSCALING, percent=41),
                                  entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))

        assert not draggable(window, 0)
        assert draggable(window, 1)

    def test_a_first_row_that_is_merely_next_can_be_dragged(self, window):
        window.show_lineup(lineup(Head(NEXT), entry("larkin/0 unsorted/a.mp4"),
                                  entry("larkin/0 unsorted/b.mp4")))

        assert draggable(window, 0)

    def test_a_drag_that_ends_in_a_move_leaves_every_row_in_the_list(self, window):
        """What Qt does after a move of its own is to remove the row the drag
        started from -- which took the row the user had just placed."""
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abc")))
        window._tree.setCurrentItem(window._tree.topLevelItem(2))

        with patch.object(queue_window, "QDrag") as drag:
            drag.return_value.exec.return_value = Qt.DropAction.MoveAction
            window._tree.startDrag(Qt.DropAction.MoveAction)

        assert window._tree.videos() == [f"larkin/0 unsorted/{name}.mp4" for name in "abc"]

    def test_where_a_drop_lands_is_the_half_of_the_row_it_was_let_go_over(self, window):
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abc")))
        tree = window._tree
        second = tree.visualItemRect(tree.topLevelItem(1))

        assert tree.dropped_row(QPoint(20, second.top() + 1)) == 1
        assert tree.dropped_row(QPoint(20, second.top() + second.height() - 1)) == 2
        assert tree.dropped_row(QPoint(20, second.top() + 400)) == 3

    def test_a_lineup_arriving_mid_drag_waits_for_the_row_to_land(self, window):
        """The refresh timer goes on firing inside the drag's own event loop,
        and a rebuild there deletes the row being dragged."""
        window.show_lineup(lineup(None, entry("larkin/0 unsorted/a.mp4")))
        window._tree._dragging = True

        window.show_lineup(lineup(None, entry("larkin/0 unsorted/z.mp4")))

        assert window._tree.videos() == ["larkin/0 unsorted/a.mp4"]

    def test_the_lineup_that_waited_is_drawn_once_the_row_lands(self, window):
        window.show_lineup(lineup(None, entry("larkin/0 unsorted/a.mp4")))
        window._tree._dragging = True
        window.show_lineup(lineup(None, entry("larkin/0 unsorted/z.mp4")))

        window._tree._dragging = False
        window._tree.drag_ended.emit()

        assert window._tree.videos() == ["larkin/0 unsorted/z.mp4"]


class TestRunningTime:
    @pytest.mark.parametrize(("seconds", "shown"), [
        (None, ""), (0.0, "0:00"), (65.0, "1:05"), (754.0, "12:34"), (3784.0, "1:03:04"),
    ])
    def test_reads_as_a_clock(self, seconds, shown):
        assert running_time(seconds) == shown
