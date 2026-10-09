"""The one decision under every surface that shows the schedule."""
from __future__ import annotations

from datetime import datetime

import pytest

from gui.schedule_state import IDLE, PAUSED, RUNNING, SCHEDULED, ScheduleStatus, schedule_state

_AT = datetime(2026, 3, 29, 14, 30)


@pytest.mark.parametrize("status", [
    ScheduleStatus(is_running=True),
    ScheduleStatus(is_paused=True),
    ScheduleStatus(next_run_at=_AT),
    ScheduleStatus(),
], ids=["running", "paused", "scheduled", "idle"])
def test_no_toolbar_label_runs_longer_than_the_longest(status):
    assert len(status.toolbar_label()) <= len(ScheduleStatus.longest_toolbar_label())


@pytest.mark.parametrize(("running", "paused", "next_run", "expected"), [
    (True, True, _AT, RUNNING),     # a run on screen outranks the pause under it
    (True, False, None, RUNNING),
    (False, True, _AT, PAUSED),     # paused with a run that would have been next
    (False, False, _AT, SCHEDULED),
    (False, False, None, IDLE),
])
def test_the_state_is_decided_in_this_order(running, paused, next_run, expected):
    assert schedule_state(running, paused, next_run) == expected
