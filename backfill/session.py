from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from backfill.decisions import (
    reclaim_from_trash,
    restore_sidecar,
    send_to_trash,
    sidecar_snapshot,
)
from backfill.queue import BackfillQueue
from backfill.vocabulary import SAME, SKIP, TRASH, UNDO, Vocabulary
from backfill.work import SerialWorker
from util.sidecar import record_action

NOTHING_TO_UNDO = "nothing to undo"
NOTHING_TO_REPEAT = "nothing to repeat"


class _Step(Protocol):
    @property
    def note(self) -> str:
        ...

    def take_effect(self, queue: BackfillQueue) -> None:
        ...

    def put_back(self, queue: BackfillQueue) -> None:
        ...

    def commit(self) -> None:
        ...

    def roll_back(self) -> None:
        pass


@dataclass
class _Labelled:
    video: Path
    action: str
    _snapshot: dict | None = field(default=None, init=False, repr=False)

    @property
    def note(self) -> str:
        return f"{self.video.name} → {self.action}"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.resolve()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.restore(self.video)

    def commit(self) -> None:
        self._snapshot = sidecar_snapshot(self.video)
        record_action(self.video, self.action)

    def roll_back(self) -> None:
        restore_sidecar(self.video, self._snapshot)


@dataclass
class _Discarded:
    video: Path
    _landed_at: Path | None = field(default=None, init=False, repr=False)

    @property
    def note(self) -> str:
        return f"{self.video.name} → Trash"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.resolve()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.restore(self.video)

    def commit(self) -> None:
        self._landed_at = send_to_trash(self.video)

    def roll_back(self) -> None:
        if self._landed_at is not None:
            reclaim_from_trash(self._landed_at, self.video)


@dataclass
class _Deferred:
    video: Path

    @property
    def note(self) -> str:
        return f"{self.video.name} → skipped"

    def take_effect(self, queue: BackfillQueue) -> None:
        queue.defer()

    def put_back(self, queue: BackfillQueue) -> None:
        queue.undefer()

    def commit(self) -> None:
        pass

    def roll_back(self) -> None:
        pass


class BackfillSession:
    def __init__(self, queue: BackfillQueue, worker: SerialWorker, vocabulary: Vocabulary) -> None:
        self._queue = queue
        self._worker = worker
        self._vocabulary = vocabulary
        self._history: list[_Step] = []

    @property
    def remaining(self) -> int:
        return self._queue.remaining

    @property
    def current(self) -> Path | None:
        return self._queue.current

    def apply(self, phrase: str) -> str | None:
        control = self._vocabulary.controls.get(phrase)
        if control == UNDO:
            return self._undo()
        if control == SAME:
            return self._repeat()

        video = self._queue.current
        if video is None:
            return None
        step = self._step_for(phrase, video)
        if step is None:
            return None
        return self._commit(step)

    def _repeat(self) -> str | None:
        video = self._queue.current
        if video is None:
            return None
        action = self._last_action()
        if action is None:
            return NOTHING_TO_REPEAT
        return self._commit(_Labelled(video, action))

    def _commit(self, step: _Step) -> str:
        step.take_effect(self._queue)
        self._worker.submit(step.commit)
        self._history.append(step)
        return step.note

    def _last_action(self) -> str | None:
        for step in reversed(self._history):
            if isinstance(step, _Labelled):
                return step.action
        return None

    def _step_for(self, phrase: str, video: Path) -> _Step | None:
        action = self._vocabulary.actions.get(phrase)
        if action is not None:
            return _Labelled(video, action)
        control = self._vocabulary.controls.get(phrase)
        if control == SKIP:
            return _Deferred(video)
        if control == TRASH:
            return _Discarded(video)
        return None

    def _undo(self) -> str:
        if not self._history:
            return NOTHING_TO_UNDO
        step = self._history.pop()

        self._worker.drain()
        step.roll_back()
        step.put_back(self._queue)
        return f"undid {step.note}"
