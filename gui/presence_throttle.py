from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer

import config
import evolver

log = logging.getLogger(__name__)


class PresenceThrottle:
    def __init__(self, is_enabled: Callable[[], bool],
                 interval_seconds: float | None = None):
        self._is_enabled = is_enabled
        interval = (config.NONAI_PRESENCE_POLL_SECONDS if interval_seconds is None
                    else interval_seconds)
        self._timer = QTimer()
        self._timer.setInterval(int(interval * 1000))
        self._timer.timeout.connect(self.poll)

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        if not self._is_enabled():
            return
        evolver.throttle_nonai_to_presence()
