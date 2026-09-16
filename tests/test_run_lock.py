"""One pipeline run on the machine at a time, whichever Evolver starts it."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

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

    def test_a_turn_a_live_process_holds_is_refused(self):
        """The other Evolver is mid-run: the files this run would move are the
        ones that one is moving."""
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")

            with pytest.raises(run_lock.Busy), run_lock.held(lock):
                pytest.fail("the run went ahead")

            assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_a_turn_left_by_a_process_that_has_ended_is_taken_over(self):
        """An Evolver killed mid-run leaves its turn held; nothing would ever
        give it back."""
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(a_process_that_has_ended()), encoding="utf-8")

            with run_lock.held(lock):
                assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_a_turn_older_than_any_run_is_taken_over_whoever_holds_its_number(self):
        """Windows hands a dead process's number to the next one, so a live
        number on a turn this old names somebody else."""
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            long_ago = time.time() - run_lock.LONGEST_RUN_SECONDS - 60
            os.utime(lock, (long_ago, long_ago))

            with run_lock.held(lock):
                assert lock.exists()

    def test_an_unreadable_turn_is_taken_over(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text("", encoding="utf-8")

            with run_lock.held(lock):
                assert lock.read_text(encoding="utf-8") == str(os.getpid())
