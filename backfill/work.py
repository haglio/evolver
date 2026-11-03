from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)


class SerialWorker:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backfill")
        self._latest: Future | None = None

    def submit(self, task: Callable[[], None]) -> None:
        self._latest = self._pool.submit(self._run, task)

    def drain(self) -> None:
        if self._latest is not None:
            self._latest.result()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)

    @staticmethod
    def _run(task: Callable[[], None]) -> None:
        try:
            task()
        except Exception:
            log.exception("Backfill could not carry out a decision")
