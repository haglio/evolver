"""The upscale queue window: what it shows, and what it says the user did.

Every video here is invented, and so is every title.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt
from PyQt6.QtGui import QDropEvent

from gui.queue_window import VIDEO_MIME, UpscaleQueueWindow, running_time
from util.upscale_lineup import (
    ASKED_FOR,
    FINISHING,
    PAUSED,
    STARTING,
    UPSCALING,
    Entry,
    Lineup,
    Now,
)


def entry(video, name=None, seconds=754.0, pinned=False):
    return Entry(video=video, name=name or video, seconds=seconds, pinned=pinned)


def lineup(now=None, *entries):
    return Lineup(now=now, up_next=tuple(entries))


def drop_of(video: str = "") -> QDropEvent:
    """The event a row dragged out of the list lands with.

    The event borrows the payload rather than owning it, so the payload is
    parked on the event: collected, it leaves the drop reading freed memory,
    which on Windows is an access violation rather than a failure.
    """
    carried = QMimeData()
    if video:
        carried.setData(VIDEO_MIME, video.encode("utf-8"))
    event = QDropEvent(QPointF(1.0, 1.0), Qt.DropAction.MoveAction, carried,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._carried = carried
    return event


@pytest.fixture
def window():
    made = UpscaleQueueWindow()
    yield made
    made.deleteLater()


class TestWhatItShows:
    def test_every_video_waiting_is_a_row_in_order(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", "Jane Doe - Alpha Study 3"),
                                  entry("larkin/0 unsorted/b.mp4", "b", seconds=None)))

        assert window._tree.videos() == ["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/b.mp4"]
        assert window._tree.topLevelItem(0).text(1) == "Jane Doe - Alpha Study 3"
        assert window._tree.topLevelItem(0).text(2) == "12:34"
        assert window._tree.topLevelItem(0).text(0) == "1"
        assert window._tree.topLevelItem(1).text(2) == ""

    def test_the_heading_counts_the_videos_and_their_hours(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", seconds=3600.0),
                                  entry("larkin/0 unsorted/b.mp4", seconds=1800.0)))

        assert window._up_next_heading.text() == "Up next — 2 videos, 1.5 hours of footage"

    def test_an_encode_in_flight_is_named_with_how_far_it_has_got(self, window):
        window.show_lineup(lineup(Now(entry("larkin/0 unsorted/a.mp4", "Jane Doe - Alpha Study 3"),
                                      UPSCALING, percent=41)))

        assert window._now_box.name_label.text() == "Jane Doe - Alpha Study 3"
        assert window._now_box.state_label.text() == "Upscaling — 41% done"
        assert window._now_box.bar.value() == 41

    def test_a_frozen_encode_says_who_froze_it(self, window):
        window.show_lineup(lineup(Now(entry("larkin/0 unsorted/a.mp4"), PAUSED, percent=41)))

        assert window._now_box.state_label.text() == (
            "Paused while you're at the computer — 41% done")

    def test_an_encode_you_asked_for_says_so(self, window):
        window.show_lineup(lineup(Now(entry("larkin/0 unsorted/a.mp4"), ASKED_FOR, percent=2)))

        assert window._now_box.state_label.text() == "Upscaling at your request — 2% done"

    def test_a_video_asked_for_and_held_back_says_what_it_is_waiting_on(self, window):
        """The machine's own word for the hold means nothing to a person: the
        window says what is being waited for."""
        window.show_lineup(lineup(Now(entry("larkin/0 unsorted/a.mp4"), STARTING,
                                      held_back="low_ram")))

        assert window._now_box.state_label.text() == (
            "Starting at your request — waiting for memory to free up")

    def test_an_encode_that_has_ended_says_the_next_run_files_it(self, window):
        window.show_lineup(lineup(Now(entry("larkin/0 unsorted/a.mp4"), FINISHING)))

        assert "next run" in window._now_box.state_label.text()
        assert not window._now_box.bar.isVisibleTo(window)

    def test_nothing_upscaling_says_so_and_invites_a_drop(self, window):
        window.show_lineup(lineup(None, entry("larkin/0 unsorted/a.mp4")))

        assert window._now_box.name_label.text() == "Nothing is being upscaled"
        assert "Drop a video here" in window._now_box.state_label.text()

    def test_the_rows_the_user_placed_carry_a_pin(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", pinned=True),
                                  entry("larkin/0 unsorted/b.mp4")))

        assert window._tree.topLevelItem(0).toolTip(0) == "You put this one here"
        assert "most watched" in window._tree.topLevelItem(1).toolTip(0)


class TestWhatItSaysTheUserDid:
    def _arrangements(self, window):
        seen = []
        window.arranged.connect(seen.append)
        return seen

    def test_a_video_dragged_to_the_top_is_the_only_one_pinned(self, window):
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abc")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/c.mp4", 0)

        assert seen == [["larkin/0 unsorted/c.mp4"]]
        assert window._tree.videos() == ["larkin/0 unsorted/c.mp4", "larkin/0 unsorted/a.mp4",
                                         "larkin/0 unsorted/b.mp4"]
        assert window._tree.topLevelItem(0).toolTip(0) == "You put this one here"

    def test_pinning_one_lower_down_pins_everything_above_it(self, window):
        """Its place is only its place if the videos it was put after stay
        where they are."""
        window.show_lineup(lineup(None, *(entry(f"larkin/0 unsorted/{name}.mp4")
                                          for name in "abcd")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/d.mp4", 2)

        assert seen == [["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/b.mp4",
                         "larkin/0 unsorted/d.mp4"]]

    def test_a_video_pushed_below_a_pinned_one_keeps_that_pin_in_the_list(self, window):
        window.show_lineup(lineup(None,
                                  entry("larkin/0 unsorted/a.mp4", pinned=True),
                                  entry("larkin/0 unsorted/b.mp4"),
                                  entry("larkin/0 unsorted/c.mp4")))
        seen = self._arrangements(window)

        window._tree.move_video("larkin/0 unsorted/c.mp4", 1)

        assert seen == [["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/c.mp4"]]

    def test_a_video_dropped_on_the_now_box_is_asked_for(self, window):
        window.show_lineup(lineup(None, entry("larkin/0 unsorted/a.mp4")))
        asked = []
        window.now_requested.connect(asked.append)

        window._now_box.dropEvent(drop_of("larkin/0 unsorted/a.mp4"))

        assert asked == ["larkin/0 unsorted/a.mp4"]

    def test_a_drop_carrying_no_video_asks_for_nothing(self, window):
        asked = []
        window.now_requested.connect(asked.append)

        window._now_box.dropEvent(drop_of())

        assert asked == []

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
