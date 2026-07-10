"""What a heard phrase does to the queue — the backfill tool's whole semantics.

Separated from the window so it can be exercised without a media backend, and so
the window is left with only what a window should do: show a clip, show a count.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from backfill.decisions import discard_as_weird, record_action
from backfill.queue import BackfillQueue
from backfill.vocabulary import ACTIONS, CONTROLS, SKIP

_SKIPPED = "Skipped"
_WEIRD = "Weird"


class BackfillSession:
    """Applies heard phrases to the queue, dispatching the file work off-thread.

    A clip leaves the screen the instant a phrase lands: the disk work — writing
    the sidecar, or moving the clip to the weird folder — is handed to
    *run_in_background* and the next clip starts playing without waiting for it.
    """

    def __init__(self, queue: BackfillQueue, run_in_background: Callable[[Callable[[], None]], None]) -> None:
        self._queue = queue
        self._run_in_background = run_in_background

    @property
    def remaining(self) -> int:
        """How many clips still need an action, deferred ones included."""
        return self._queue.remaining

    @property
    def current(self) -> Path | None:
        """The clip that should be on screen, or None once the queue is empty."""
        return self._queue.current

    def apply(self, phrase: str) -> str | None:
        """React to *phrase*; returns what it did, or None if it meant nothing here."""
        clip = self._queue.current
        if clip is None:
            return None

        action = ACTIONS.get(phrase)
        if action is not None:
            self._queue.resolve()
            self._run_in_background(lambda: record_action(clip, action))
            return action

        control = CONTROLS.get(phrase)
        if control is None:
            return None
        if control == SKIP:
            self._queue.defer()
            return _SKIPPED

        self._queue.resolve()
        self._run_in_background(lambda: discard_as_weird(clip))
        return _WEIRD
