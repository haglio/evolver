"""Timer-based pipeline scheduler with run-guard, pause/resume, and clock alignment."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class PipelineScheduler(QObject):
    """Fires run_requested at clock-aligned intervals (e.g. :00, :10, :20).

    The scheduler silently drops ticks while a run is in progress (any tick
    that arrives mid-run is ignored). Pause/resume controls the timer.
    """

    run_requested = pyqtSignal(str)  # "scheduled" or "manual"
    status_changed = pyqtSignal()    # emitted when state changes that affect display

    def __init__(self, interval_minutes: int = 10, parent=None,
                 now: Callable[[], datetime] = datetime.now):
        super().__init__(parent)
        self._running = False
        self._paused = False
        self._interval_minutes = interval_minutes
        # The clock is a seam: a test parks it just short of a slot boundary
        # and gets a real timer firing in milliseconds. The interval is never
        # one — the spin box offers 1..120 and EvolverSettings.load clamps a
        # hand-edited file to the same floor, because _schedule_next divides
        # by it.
        self._now = now
        self._next_run_at: datetime | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.tick)

    def start(self):
        if not self._paused:
            self._schedule_next()

    def stop(self):
        self._timer.stop()
        self._next_run_at = None
        self.status_changed.emit()

    def pause(self):
        self._paused = True
        self._timer.stop()
        self._next_run_at = None
        self.status_changed.emit()

    def resume(self):
        self._paused = False
        self._schedule_next()

    def run_now(self):
        if not self._running:
            self.run_requested.emit("manual")

    def mark_running(self):
        self._running = True
        self.status_changed.emit()

    def mark_idle(self):
        self._running = False
        self._schedule_next()

    def set_interval_minutes(self, minutes: int):
        self._interval_minutes = minutes
        if not self._paused:
            self._schedule_next()

    @property
    def interval_minutes(self) -> int:
        return self._interval_minutes

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def next_run_at(self) -> datetime | None:
        return self._next_run_at

    def _schedule_next(self):
        """Set a one-shot timer for the next clock-aligned interval."""
        now = self._now()
        interval = self._interval_minutes

        # Align to clock: find next minute that's a multiple of interval
        current_minute = now.hour * 60 + now.minute
        next_slot = ((current_minute // interval) + 1) * interval
        next_hour, next_minute = divmod(next_slot, 60)

        target = now.replace(second=0, microsecond=0)
        if next_hour >= 24:
            # Wraps to next day
            target = target.replace(hour=0, minute=0) + timedelta(days=1)
            next_hour, next_minute = divmod(next_slot % (24 * 60), 60)
            target = target.replace(hour=next_hour, minute=next_minute)
        else:
            target = target.replace(hour=next_hour, minute=next_minute)

        ms_until = max(0, int((target - now).total_seconds() * 1000))
        self._next_run_at = target
        self._timer.start(ms_until)
        self.status_changed.emit()

    def tick(self):
        """What one firing of the interval timer does.

        Public so tests can drive a tick deterministically instead of waiting
        on the wall clock; the timer connects here and nothing else calls it.
        """
        if not self._running:
            self.run_requested.emit("scheduled")
        # Always schedule the next tick (if the run is in progress, mark_idle
        # will call _schedule_next when it finishes)
        if not self._running:
            self._schedule_next()
