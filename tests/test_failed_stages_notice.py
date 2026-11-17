from __future__ import annotations

import unittest

from gui.failed_stages_notice import FailedStagesNotice
from gui.run_record import RunRecord


def a_run(*stages):
    return RunRecord(id="r", started_at="2026-01-01T18:20:00", finished_at="2026-01-01T18:21:00",
                     duration_seconds=60.0, trigger="scheduled", status="error",
                     stages=list(stages))


def a_stage(key, status):
    return {"name": key, "status": status, "duration_seconds": 1.0, "result": None}


class TestFailedStagesNotice(unittest.TestCase):
    def test_a_run_with_a_failed_stage_opens_an_error_window_naming_it(self):
        shown = []
        FailedStagesNotice(show=lambda title, message: shown.append((title, message))).after_run(
            a_run(a_stage("sort", "completed"), a_stage("watch_weights", "error")))

        assert [title for title, _message in shown] == ["Evolver - Stage Error"]
        assert "Update weights" in shown[0][1]
        assert "Sort inbox" not in shown[0][1]

    def test_a_run_whose_stages_only_warned_opens_no_window(self):
        shown = []
        FailedStagesNotice(show=lambda *window: shown.append(window)).after_run(
            a_run(a_stage("strays", "warning"), a_stage("sort", "completed")))

        assert shown == []

    def test_a_run_that_fails_while_its_window_is_still_open_opens_no_second_one(self):
        shown = []
        notice = FailedStagesNotice(
            show=lambda *window: shown.append(window) or notice.after_run(
                a_run(a_stage("watch_weights", "error"))))

        notice.after_run(a_run(a_stage("watch_weights", "error")))

        assert len(shown) == 1
