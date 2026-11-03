from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class BackgroundQueue(QObject):
    _answered = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evolver-background")
        self._answered.connect(lambda then, answer: then(answer))

    def run(self, work: Callable[[], object],
            then: Callable[[object], None] | None = None) -> None:
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
        self._worker.shutdown(wait=False, cancel_futures=True)
