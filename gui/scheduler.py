"""Timer-based pipeline scheduler with run-guard and pause/resume."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class PipelineScheduler(QObject):
    """Fires run_requested on a configurable interval, with manual trigger support.

    The scheduler silently drops ticks while a run is in progress (mirrors the
    Windows Task Scheduler IgnoreNew policy). Pause/resume controls the timer.
    """

    run_requested = pyqtSignal(str)  # "scheduled" or "manual"

    def __init__(self, interval_minutes: int = 10, parent=None):
        super().__init__(parent)
        self._running = False
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_minutes * 60 * 1000)
        self._timer.timeout.connect(self._on_tick)

    def start(self):
        if not self._paused:
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def pause(self):
        self._paused = True
        self._timer.stop()

    def resume(self):
        self._paused = False
        self._timer.start()

    def run_now(self):
        if not self._running:
            self.run_requested.emit("manual")

    def mark_running(self):
        self._running = True

    def mark_idle(self):
        self._running = False

    def set_interval_minutes(self, minutes: int):
        self._timer.setInterval(minutes * 60 * 1000)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _on_tick(self):
        if not self._running:
            self.run_requested.emit("scheduled")
