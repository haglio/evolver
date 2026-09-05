"""The one decision behind every surface that shows the schedule."""

from datetime import datetime

import pytest

from gui.schedule_state import IDLE, PAUSED, RUNNING, SCHEDULED, schedule_state

_AT = datetime(2026, 3, 29, 14, 30)


@pytest.mark.parametrize(("running", "paused", "next_run", "expected"), [
    (True, True, _AT, RUNNING),     # a run on screen outranks the pause behind it
    (True, False, None, RUNNING),
    (False, True, _AT, PAUSED),     # paused with a run that would have been next
    (False, False, _AT, SCHEDULED),
    (False, False, None, IDLE),
])
def test_the_state_is_decided_in_this_order(running, paused, next_run, expected):
    assert schedule_state(running, paused, next_run) == expected
