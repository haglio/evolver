from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from gui.schedule_state import ScheduleStatus

_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24


class PipelineScheduler(QObject):
    run_requested = Signal(str)
    status_changed = Signal(object)

    def __init__(self, interval_minutes: int = 10, parent=None,
                 now: Callable[[], datetime] = datetime.now):
        super().__init__(parent)
        self._running = False
        self._paused = False
        self._interval_minutes = interval_minutes
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
        self._announce()

    def pause(self):
        self._paused = True
        self._timer.stop()
        self._next_run_at = None
        self._announce()

    def resume(self):
        self._paused = False
        self._schedule_next()

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def run_now(self):
        if not self._running:
            self.run_requested.emit("manual")

    def mark_running(self):
        self._running = True
        self._announce()

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
    def status(self) -> ScheduleStatus:
        return ScheduleStatus(self._running, self._paused, self._next_run_at)

    def _announce(self):
        self.status_changed.emit(self.status)

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
        now = self._now()
        interval = self._interval_minutes

        current_minute = now.hour * _MINUTES_PER_HOUR + now.minute
        next_slot = ((current_minute // interval) + 1) * interval
        next_hour, next_minute = divmod(next_slot, _MINUTES_PER_HOUR)

        target = now.replace(second=0, microsecond=0)
        if next_hour >= _HOURS_PER_DAY:
            target = target.replace(hour=0, minute=0) + timedelta(days=1)
            next_hour, next_minute = divmod(next_slot % (_HOURS_PER_DAY * _MINUTES_PER_HOUR),
                                            _MINUTES_PER_HOUR)
            target = target.replace(hour=next_hour, minute=next_minute)
        else:
            target = target.replace(hour=next_hour, minute=next_minute)

        ms_until = max(0, int((target - now).total_seconds() * 1000))
        self._next_run_at = target
        self._timer.start(ms_until)
        self._announce()

    def tick(self):
        if not self._running:
            self.run_requested.emit("scheduled")
        if not self._running:
            self._schedule_next()
