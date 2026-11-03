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
    is_running: bool = False
    is_paused: bool = False
    next_run_at: datetime | None = None

    @property
    def state(self) -> str:
        return schedule_state(self.is_running, self.is_paused, self.next_run_at)

    def headline(self) -> str:
        if self.state == SCHEDULED:
            return f"Scheduled for {self.next_run_at.strftime(_CLOCK)}"
        return {RUNNING: "Running", PAUSED: "Paused"}.get(self.state, "Scheduled")

    def next_run_text(self) -> str:
        if self.state != SCHEDULED:
            return ""
        return f"Next run: {self.next_run_at.strftime(_CLOCK)}"

    def activity(self) -> str:
        if self.state == RUNNING:
            return "Running..."
        if self.state == PAUSED:
            return "Paused"
        return self.next_run_text()

    def toolbar_label(self) -> str:
        if self.state == PAUSED:
            return "No upcoming runs scheduled (inactive)"
        return self.activity()

    @classmethod
    def longest_toolbar_label(cls) -> str:
        return cls(is_paused=True).toolbar_label()
