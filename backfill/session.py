"""What a heard phrase does to the queue — the backfill tool's whole semantics.

Separated from the window so it can be exercised without a media backend, and so
the window is left with only what a window should do: show a clip, show a count.

Every decision is a :class:`_Step` that knows how to take itself back, in both
places it landed: the queue, and the disk.  The session keeps them on a stack, so
"undo" walks back through a whole run of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backfill.decisions import (
    discard_as_weird,
    reclaim_from_weird,
    record_action,
    restore_sidecar,
    sidecar_snapshot,
)
from backfill.queue import BackfillQueue
from backfill.vocabulary import ACTIONS, CONTROLS, SKIP, UNDO
from backfill.work import SerialWorker

NOTHING_TO_UNDO = "nothing to undo"


@dataclass
class _Labelled:
    """The viewer named the act; the clip keeps whatever else its sidecar held."""

    clip: Path
    action: str
    _snapshot: dict | None = field(default=None, init=False, repr=False)

    @property
    def note(self) -> str:
        return f"{self.clip.name} → {self.action}"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.resolve()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.restore(self.clip)

    def commit(self) -> None:
        self._snapshot = sidecar_snapshot(self.clip)
        record_action(self.clip, self.action)

    def roll_back(self) -> None:
        restore_sidecar(self.clip, self._snapshot)


@dataclass
class _Discarded:
    """The clip was weird; it now sits in the weird folder, awaiting the purge stage."""

    clip: Path
    _landed_at: Path | None = field(default=None, init=False, repr=False)

    @property
    def note(self) -> str:
        return f"{self.clip.name} → weird"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.resolve()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.restore(self.clip)

    def commit(self) -> None:
        self._landed_at = discard_as_weird(self.clip)

    def roll_back(self) -> None:
        if self._landed_at is not None:  # the move failed; there is nothing to reclaim
            reclaim_from_weird(self._landed_at, self.clip)


@dataclass
class _Deferred:
    """Not now — the clip goes to the back of the queue, untouched on disk."""

    clip: Path

    @property
    def note(self) -> str:
        return f"{self.clip.name} → skipped"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.defer()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.undefer()

    def commit(self) -> None:
        """A deferral touches no file."""

    def roll_back(self) -> None:
        """A deferral touches no file."""


class BackfillSession:
    """Applies heard phrases to the queue, dispatching the file work off-thread.

    A clip leaves the screen the instant a phrase lands: the disk work — writing
    the sidecar, or moving the clip to the weird folder — goes to *worker* and the
    next clip starts playing without waiting for it.
    """

    def __init__(self, queue: BackfillQueue, worker: SerialWorker) -> None:
        self._queue = queue
        self._worker = worker
        self._history: list[_Labelled | _Discarded | _Deferred] = []

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
        if CONTROLS.get(phrase) == UNDO:
            return self._undo()

        clip = self._queue.current
        if clip is None:
            return None
        step = self._step_for(phrase, clip)
        if step is None:
            return None

        step.take_effect(self._queue)
        self._worker.submit(step.commit)
        self._history.append(step)
        return step.note

    def _step_for(self, phrase: str, clip: Path):
        action = ACTIONS.get(phrase)
        if action is not None:
            return _Labelled(clip, action)
        control = CONTROLS.get(phrase)
        if control is None:
            return None
        return _Deferred(clip) if control == SKIP else _Discarded(clip)

    def _undo(self) -> str:
        """Take the last decision back, in the queue and on disk."""
        if not self._history:
            return NOTHING_TO_UNDO
        step = self._history.pop()

        # The decision's own file work may still be in flight, and reversing a write
        # that has not happened would leave the clip labelled. Wait for it, then
        # reverse it here rather than on the worker: the window reloads the restored
        # clip the moment this returns, and a discarded clip has to be back in place
        # by then for the player to find it.
        self._worker.drain()
        step.roll_back()
        step.put_back(self._queue)
        return f"undid {step.note}"
