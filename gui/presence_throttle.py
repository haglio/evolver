"""A fast poll that keeps the in-flight non-AI encode in step with the user.

The pipeline tick is slow -- ten minutes by default -- and the encode it
supervises runs for hours, so without this, returning to the machine would
leave a multi-hour encode holding the GPU until the next tick noticed. This
fires far more often and does one thing: park the encode when the user is back,
thaw it when they idle out again.

It holds a timer and a callback and nothing else. Which stage owns the encode
is ``evolver``'s to know -- the repo's layering is ``util <- tasks <- evolver
<- gui``, and this is the gui side of that door.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer

import config
import evolver

log = logging.getLogger(__name__)


class PresenceThrottle:
    """Polls while it is running, and asks *is_enabled* before each poll.

    The opt-in is read at every tick rather than at construction: the tray's
    toggle flips it while this is running, and a throttle that had to be
    rebuilt to notice would be a second place the setting lives.
    """

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
        """One check. Does nothing at all unless the user has opted in."""
        if not self._is_enabled():
            return
        evolver.throttle_nonai_to_presence()
