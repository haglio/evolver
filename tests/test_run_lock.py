from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import config
from tests.temp_helpers import workspace_temp_dir
from util import run_lock


def a_process_that_has_ended() -> int:
    ended = subprocess.Popen([sys.executable, "-c", "pass"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    ended.wait()
    return ended.pid


class TestTheTurn:
    def test_a_free_turn_is_taken_and_given_back(self):
        with workspace_temp_dir() as root:
            lock = root / "state" / "pipeline.lock"

            with run_lock.held(lock):
                assert lock.read_text(encoding="utf-8") == str(os.getpid())

            assert not lock.exists()

    def test_a_second_run_is_refused_the_held_turn(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")

            with pytest.raises(run_lock.Busy), run_lock.held(lock):
                pytest.fail("a command-line run went ahead beside the tray's: two sorts of one inbox at once")

            assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_a_turn_left_by_a_process_that_has_ended_is_taken_over(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(a_process_that_has_ended()), encoding="utf-8")

            with run_lock.held(lock):
                assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_a_turn_older_than_any_run_is_taken_over_whoever_holds_its_number(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            long_ago = time.time() - run_lock.LONGEST_RUN_SECONDS - 60
            os.utime(lock, (long_ago, long_ago))

            with run_lock.held(lock):
                assert lock.exists()

    def test_a_turn_outlasts_the_trays_watchdog_fivefold(self):
        assert run_lock.LONGEST_RUN_SECONDS >= 5 * config.PIPELINE_WALL_TIMEOUT_SECONDS, "a turn this old was left by a run that died"

    def test_an_unreadable_turn_is_taken_over(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text("", encoding="utf-8")

            with run_lock.held(lock):
                assert lock.read_text(encoding="utf-8") == str(os.getpid())
