from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gui.run_record import RunRecord, every_run, utc_time
from tasks.stages import ALL_STAGES

_ROW_OF_STAGE = {stage: row for row, stage in enumerate(ALL_STAGES)}


@dataclass(frozen=True)
class RunHistory:
    started: np.ndarray
    durations: np.ndarray

    @classmethod
    def of(cls, records: Iterable[RunRecord]) -> RunHistory:
        started: list[float] = []
        durations: list[list[float]] = []
        for record in records:
            try:
                moment = utc_time(record.started_at)
            except ValueError:
                continue
            started.append(moment.timestamp())
            durations.append(_seconds_by_stage(record))
        oldest_first = np.argsort(started, kind="stable")
        return cls(
            started=np.array(started, dtype=float)[oldest_first],
            durations=np.array(durations, dtype=float).reshape(-1, len(ALL_STAGES))
            [oldest_first].T,
        )

    @classmethod
    def read(cls, runs_dir: Path) -> RunHistory:
        return cls.of(every_run(runs_dir))

    def __len__(self) -> int:
        return len(self.started)


def _seconds_by_stage(record: RunRecord) -> list[float]:
    seconds = [0.0] * len(ALL_STAGES)
    for stage in record.stages:
        row = _ROW_OF_STAGE.get(stage["name"])
        if row is not None:
            seconds[row] = stage["duration_seconds"]
    return seconds
