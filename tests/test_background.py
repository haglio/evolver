"""Work the windows hand off their own thread, and the answers that come back to it."""
from __future__ import annotations

import threading
import time

import pytest

from gui.background import BackgroundQueue
from tests.gui_support import QAPP


def pump_until(condition, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QAPP.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def queue():
    made = BackgroundQueue()
    yield made
    made.stop()


def test_the_work_is_done_off_this_thread_and_its_answer_comes_back_on_it(queue):
    answers = []

    queue.run(threading.current_thread,
              then=lambda worker: answers.append((worker, threading.current_thread())))

    assert pump_until(lambda: answers)
    worker, answered_on = answers[0]
    assert worker is not threading.main_thread()
    assert answered_on is threading.main_thread()


def test_work_is_done_in_the_order_it_was_asked_for(queue):
    """Switching the arrow on and straight off again must end with it off."""
    done = []

    for step in range(5):
        queue.run(lambda step=step: time.sleep(0.01 * (5 - step)) or done.append(step))
    queue.run(lambda: None, then=lambda _: done.append("answered"))

    assert pump_until(lambda: "answered" in done)
    assert done == [0, 1, 2, 3, 4, "answered"]


def test_work_that_fails_is_logged_and_what_follows_still_runs(queue, caplog):
    answers = []

    def fails():
        raise OSError("the library drive went away")

    queue.run(fails, then=answers.append)
    queue.run(lambda: "next", then=answers.append)

    assert pump_until(lambda: answers)
    assert answers == ["next"]
    assert "the library drive went away" in caplog.text
