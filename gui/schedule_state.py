"""What the schedule is doing, decided and worded once for every surface.

The tray's tooltip, the two status lines at the top of its menu and the
window's toolbar label used to each decide this for themselves, and decided it
differently: the tray put a run in flight ahead of a pause, the window put the
pause first, so pausing while a pipeline was running read "Running..." in the
tray and "inactive" in the window at the same moment.  A run on screen is the
fact the user is looking at, and a pause stops the schedule after it -- so
running outranks paused, here, for both.

Three chains over the same three booleans, each with its own ``strftime`` and
its own wording for an idle schedule, is how they came apart the first time.
The scheduler hands out a :class:`ScheduleStatus` instead, and every word a
surface shows comes off it -- including the one deliberate difference, the
window's longer sentence for a paused schedule, which reads as a sentence
because it sits in a wide toolbar rather than in a hover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RUNNING = "running"
PAUSED = "paused"
SCHEDULED = "scheduled"
IDLE = "idle"

_CLOCK = "%H:%M"


def schedule_state(is_running: bool, is_paused: bool, next_run_at: datetime | None) -> str:
    if is_running:
        return RUNNING
    if is_paused:
        return PAUSED
    if next_run_at:
        return SCHEDULED
    return IDLE


@dataclass(frozen=True)
class ScheduleStatus:
    """The schedule as the scheduler knows it, and as the surfaces read it."""

    is_running: bool = False
    is_paused: bool = False
    next_run_at: datetime | None = None

    @property
    def state(self) -> str:
        return schedule_state(self.is_running, self.is_paused, self.next_run_at)

    def headline(self) -> str:
        """One word for the state, for the menu's status line."""
        return {RUNNING: "Running", PAUSED: "Paused"}.get(self.state, "Scheduled")

    def next_run_text(self) -> str:
        """When the next run is, or "" when none is coming."""
        if self.state != SCHEDULED:
            return ""
        return f"Next run: {self.next_run_at.strftime(_CLOCK)}"

    def activity(self) -> str:
        """What is happening, in a hover's worth of words -- "" when nothing is."""
        if self.state == RUNNING:
            return "Running..."
        if self.state == PAUSED:
            return "Paused"
        return self.next_run_text()

    def toolbar_label(self) -> str:
        """The same, for a wide toolbar, where a paused schedule can say why."""
        if self.state == PAUSED:
            return "No upcoming runs scheduled (inactive)"
        return self.activity()
