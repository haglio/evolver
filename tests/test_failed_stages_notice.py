from __future__ import annotations

import unittest

from shared_ui.testing import alert_shown

from gui.failed_stages_notice import FailedStagesNotice
from gui.run_record import RunRecord


def a_run(*stages, started_at="2026-01-01T18:20:00"):
    return RunRecord(id="r", started_at=started_at, finished_at="2026-01-01T18:21:00",
                     duration_seconds=60.0, trigger="scheduled", status="error",
                     stages=list(stages))


def a_stage(key, status):
    return {"name": key, "status": status, "duration_seconds": 1.0, "result": None}


class TestFailedStagesNotice(unittest.TestCase):
    def test_a_run_with_a_failed_stage_opens_an_error_window_naming_it(self):
        shown = []
        FailedStagesNotice(show=lambda title, message, **_: shown.append((title, message))).after_run(
            a_run(a_stage("sort", "completed"), a_stage("watch_weights", "error")))

        assert [title for title, _message in shown] == ["Evolver - Stage Error"]
        assert "Update weights" in shown[0][1]
        assert "Sort inbox" not in shown[0][1]

    def test_a_run_whose_stages_only_warned_opens_no_window(self):
        shown = []
        FailedStagesNotice(show=lambda *window, **_: shown.append(window)).after_run(
            a_run(a_stage("strays", "warning"), a_stage("sort", "completed")))

        assert shown == []

    def test_a_run_that_fails_while_its_window_is_still_open_opens_no_second_one(self):
        shown = []
        notice = FailedStagesNotice(
            show=lambda *window, **_: shown.append(window) or notice.after_run(
                a_run(a_stage("watch_weights", "error"))))

        notice.after_run(a_run(a_stage("watch_weights", "error")))

        assert len(shown) == 1

    @alert_shown()
    def test_the_same_stage_failing_in_a_later_run_is_the_same_error_so_its_window_is_not_shown_again(
            self, show_alert):
        notice = FailedStagesNotice()

        notice.after_run(a_run(a_stage("watch_weights", "error"), started_at="2026-01-01T18:20:00"))
        notice.after_run(a_run(a_stage("watch_weights", "error"), started_at="2026-01-01T18:30:00"))

        assert show_alert.call_count == 1
