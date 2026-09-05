"""Which state the schedule is in, decided once for every surface that shows it.

The tray's tooltip and menu and the window's toolbar label used to each decide
this for themselves, and decided it differently: the tray put a run in flight
ahead of a pause, the window put the pause first, so pausing while a pipeline
was running read "Running..." in the tray and "inactive" in the window at the
same moment.  A run on screen is the fact the user is looking at, and a pause
stops the schedule after it -- so running outranks paused, here, for both.
"""

from __future__ import annotations

from datetime import datetime

RUNNING = "running"
PAUSED = "paused"
SCHEDULED = "scheduled"
IDLE = "idle"


def schedule_state(is_running: bool, is_paused: bool, next_run_at: datetime | None) -> str:
    if is_running:
        return RUNNING
    if is_paused:
        return PAUSED
    if next_run_at:
        return SCHEDULED
    return IDLE
