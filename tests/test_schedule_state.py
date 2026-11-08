from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gui.schedule_state import IDLE, PAUSED, RUNNING, SCHEDULED, ScheduleStatus, schedule_state

_AT = datetime(2026, 3, 29, 14, 30, tzinfo=UTC)


@pytest.mark.parametrize("status", [
    ScheduleStatus(is_running=True),
    ScheduleStatus(is_paused=True),
    ScheduleStatus(next_run_at=_AT),
    ScheduleStatus(),
], ids=["running", "paused", "scheduled", "idle"])
def test_no_toolbar_label_runs_longer_than_the_longest(status):
    assert len(status.toolbar_label()) <= len(ScheduleStatus.longest_toolbar_label())


@pytest.mark.parametrize(("running", "paused", "next_run", "expected"), [
    (True, True, _AT, RUNNING),
    (True, False, None, RUNNING),
    (False, True, _AT, PAUSED),
    (False, False, _AT, SCHEDULED),
    (False, False, None, IDLE),
])
def test_the_state_is_decided_in_this_order_a_run_on_screen_outranking_a_pause_that_stops_only_what_follows(running, paused, next_run, expected):
    assert schedule_state(running, paused, next_run) == expected
