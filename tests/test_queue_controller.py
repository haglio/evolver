from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QWidget

from gui.queue_controller import QueueController
from tests.gui_support import EMPTY_QUEUE, DoneWhileTheTestsPatchesStand


@pytest.fixture
def parent():
    widget = QWidget()
    yield widget
    widget.close()
    widget.deleteLater()


def _opened(parent) -> tuple[QueueController, MagicMock]:
    controller = QueueController(parent, DoneWhileTheTestsPatchesStand())
    with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
        controller.show()
    return controller, queue


def _heard(signal) -> list:
    heard = []
    signal.connect(lambda *carried: heard.append(carried))
    return heard


class TestTheQueueWindowsLifetime:
    def test_the_queue_is_read_off_the_windows_thread(self, parent):
        background = MagicMock()
        controller = QueueController(parent, background)

        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
            controller.show()
            queue.assert_not_called()
            work, then = (background.run.call_args.args[0],
                          background.run.call_args.kwargs["then"])
            then(work())

        queue.assert_called_once_with()
        assert controller._window.current._heading.text() == "Nothing is waiting to be upscaled"

    def test_opening_it_hands_it_the_queue_as_it_stands(self, parent):
        controller, queue = _opened(parent)

        queue.assert_called_once_with()
        assert controller.is_on_screen

    def test_a_second_open_raises_the_one_already_up(self, parent):
        controller, _lineup = _opened(parent)
        first = controller._window.current

        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE):
            controller.show()

        assert controller._window.current is first

    def test_it_asks_to_be_redrawn_while_it_is_open(self, parent):
        controller, _lineup = _opened(parent)

        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
            controller._window.current.refresh_wanted.emit()

        queue.assert_called_once_with()

    def test_with_no_window_up_there_is_nothing_to_redraw(self, parent):
        controller = QueueController(parent, DoneWhileTheTestsPatchesStand())

        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
            controller.refresh()

        queue.assert_not_called()


class TestTheQueueWindowsVerbs:
    def test_rearranging_it_pins_the_order_through_the_pipeline_module(self, parent):
        controller, _lineup = _opened(parent)

        with patch("evolver.arrange_upscale_queue") as arranged:
            controller._window.current.arranged.emit(["lagoon/0 unsorted/a.mp4"])

        arranged.assert_called_once_with(["lagoon/0 unsorted/a.mp4"])

    def test_a_video_put_first_goes_first_and_asks_for_no_run(self, parent):
        controller, _lineup = _opened(parent)
        runs_wanted = _heard(controller.run_wanted)

        with patch("evolver.upscale_next") as put_first, \
             patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
            controller._window.current.placed_first.emit("lagoon/0 unsorted/a.mp4")

        put_first.assert_called_once_with("lagoon/0 unsorted/a.mp4")
        asked.assert_not_called()
        assert runs_wanted == []
        queue.assert_called_once_with()

    def test_asking_for_one_now_records_it_and_asks_for_a_run_at_once(self, parent):
        controller, _lineup = _opened(parent)
        runs_wanted = _heard(controller.run_wanted)

        with patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_queue", return_value=EMPTY_QUEUE):
            controller._window.current.now_requested.emit("lagoon/0 unsorted/a.mp4")

        asked.assert_called_once_with("lagoon/0 unsorted/a.mp4")
        assert runs_wanted == [("manual",)]

    def test_withdrawing_the_ask_asks_for_the_presence_poll_before_redrawing(self, parent):
        controller, _lineup = _opened(parent)
        polls_wanted = _heard(controller.presence_poll_wanted)

        with patch("evolver.withdraw_upscale_now") as withdrawn, \
             patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue:
            controller._window.current.now_withdrawn.emit()

        withdrawn.assert_called_once_with()
        assert polls_wanted == [()]
        queue.assert_called_once_with()
