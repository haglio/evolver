"""The Upscale Queue window's controller: it opens the window, keeps it drawn, and
answers the window's verbs through the pipeline module, off the window's thread."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QWidget

from gui.queue_controller import QueueController
from tests.gui_support import EMPTY_QUEUE, DoneAtOnce


@pytest.fixture
def parent():
    """The window the queue window is parented to, taken down with it after the test."""
    widget = QWidget()
    yield widget
    widget.close()
    widget.deleteLater()


def _opened(parent) -> tuple[QueueController, MagicMock]:
    controller = QueueController(parent, DoneAtOnce())
    with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
        controller.show()
    return controller, lineup


def _heard(signal) -> list:
    """Every emission of *signal*, each as the tuple of what it carried."""
    heard = []
    signal.connect(lambda *carried: heard.append(carried))
    return heard


class TestTheQueueWindowsLifetime:
    def test_the_queue_is_read_off_the_windows_thread(self, parent):
        """A run holding the stage, or a slow library drive, must not stop
        the window answering the mouse."""
        background = MagicMock()
        controller = QueueController(parent, background)

        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            controller.show()
            lineup.assert_not_called()
            work, then = (background.run.call_args.args[0],
                          background.run.call_args.kwargs["then"])
            then(work())

        lineup.assert_called_once_with()
        assert controller._window.current._heading.text() == "Nothing is waiting to be upscaled"

    def test_opening_it_hands_it_the_queue_as_it_stands(self, parent):
        controller, lineup = _opened(parent)

        lineup.assert_called_once_with()
        assert controller.is_on_screen

    def test_a_second_open_raises_the_one_already_up(self, parent):
        controller, _lineup = _opened(parent)
        first = controller._window.current

        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE):
            controller.show()

        assert controller._window.current is first

    def test_it_asks_to_be_redrawn_while_it_is_open(self, parent):
        """Presence parks and thaws the encode between runs, and the percent
        climbs the whole time."""
        controller, _lineup = _opened(parent)

        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            controller._window.current.refresh_wanted.emit()

        lineup.assert_called_once_with()

    def test_with_no_window_up_there_is_nothing_to_redraw(self, parent):
        controller = QueueController(parent, DoneAtOnce())

        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            controller.refresh()

        lineup.assert_not_called()


class TestTheQueueWindowsVerbs:
    def test_rearranging_it_pins_the_order_through_the_pipeline_module(self, parent):
        controller, _lineup = _opened(parent)

        with patch("evolver.arrange_upscale_queue") as arranged:
            controller._window.current.arranged.emit(["lagoon/0 unsorted/a.mp4"])

        arranged.assert_called_once_with(["lagoon/0 unsorted/a.mp4"])

    def test_a_video_put_first_goes_first_and_asks_for_no_run(self, parent):
        """Dragging a video to the top is ordering, not asking: it waits for
        the usual moment like any other."""
        controller, _lineup = _opened(parent)
        runs_wanted = _heard(controller.run_wanted)

        with patch("evolver.upscale_next") as put_first, \
             patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            controller._window.current.placed_first.emit("lagoon/0 unsorted/a.mp4")

        put_first.assert_called_once_with("lagoon/0 unsorted/a.mp4")
        asked.assert_not_called()
        assert runs_wanted == []
        lineup.assert_called_once_with()

    def test_asking_for_one_now_records_it_and_asks_for_a_run_at_once(self, parent):
        """The stage starts encodes on a run and nowhere else, so asking for
        one has to bring the next run forward rather than wait ten minutes."""
        controller, _lineup = _opened(parent)
        runs_wanted = _heard(controller.run_wanted)

        with patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE):
            controller._window.current.now_requested.emit("lagoon/0 unsorted/a.mp4")

        asked.assert_called_once_with("lagoon/0 unsorted/a.mp4")
        assert runs_wanted == [("manual",)]

    def test_withdrawing_the_ask_asks_for_the_presence_poll_before_redrawing(self, parent):
        """The poll that parks the encode fires every twenty seconds; the click
        that hands it back should not wait them out."""
        controller, _lineup = _opened(parent)
        polls_wanted = _heard(controller.presence_poll_wanted)

        with patch("evolver.withdraw_upscale_now") as withdrawn, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            controller._window.current.now_withdrawn.emit()

        withdrawn.assert_called_once_with()
        assert polls_wanted == [()]
        lineup.assert_called_once_with()
