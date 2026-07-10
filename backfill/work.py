"""The one thread the backfill tool's file work happens on."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)


class SerialWorker:
    """Runs file work off the window's thread, one task at a time, in order.

    Order is the point.  Decisions are recorded in the order they were spoken, and
    :meth:`drain` lets an undo wait for the decision it is about to reverse — a
    single worker means waiting on the last task waits on every task before it.

    A task that raises is logged and dropped: the clip it belonged to has already
    left the queue, so an exception escaping into a discarded Future would look
    exactly like a clip that was labelled successfully.
    """

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backfill")
        self._latest: Future | None = None

    def submit(self, task: Callable[[], None]) -> None:
        """Queue *task* to run after everything already submitted."""
        self._latest = self._pool.submit(self._run, task)

    def drain(self) -> None:
        """Block until every submitted task has finished."""
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
