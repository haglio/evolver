"""Work a window asks for, done off the window's thread, in the order it was asked.

The queue window's verbs and its lineup reach into the non-AI stage, which a
pipeline run may be holding for as long as it takes to start an encode or file
a finished one. Waited for on the window's own thread, that hold is a window
that stops answering the mouse.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class BackgroundQueue(QObject):
    """One worker thread, and a way back to this one for what it finds."""

    _answered = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evolver-background")
        self._answered.connect(lambda then, answer: then(answer))

    def run(self, work: Callable[[], object],
            then: Callable[[object], None] | None = None) -> None:
        """Do *work* on the worker, then hand its answer to *then* on this thread."""
        self._worker.submit(self._do, work, then)

    def _do(self, work, then) -> None:
        try:
            answer = work()
        except Exception:
            log.exception("Work handed off the window's thread failed")
            return
        if then is not None:
            self._answered.emit(then, answer)

    def stop(self) -> None:
        """Drop whatever has not started; what has finishes on its own."""
        self._worker.shutdown(wait=False, cancel_futures=True)
