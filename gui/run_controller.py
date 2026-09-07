"""One pipeline run at a time: the worker, its watchdog, and the popup.

Everything about *running* a run lives here — the re-entry guard that keeps a
second pipeline off a library the first still owns, the wall-clock watchdog and
its cooperative stop, and the progress popup's whole lifetime. What it does not
know is who is watching: it says a run began, a run ended, a run finished with
this record, a run failed with this message, a run overran. The tray's spinner,
the scheduler's gate, the history refresh and whether a balloon is shown at all
are the app's answer to those, not this object's business.

The watchdog never pretends: a stage mid-move cannot be cut without risking a
half-moved library, so an overrun asks the pipeline to stop between stages and
leaves everything else exactly as it was. The worker stays referenced with its
signals connected — it is the re-entry guard, and its eventual finish is what
re-opens scheduling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

import config
from gui.progress_popup import ProgressPopup
from gui.worker import PipelineWorker

log = logging.getLogger(__name__)


class RunController(QObject):
    """Starts pipeline runs, watches the clock, and says what happened."""

    run_started = pyqtSignal()
    run_ended = pyqtSignal()
    run_finished = pyqtSignal(object)  # RunRecord
    run_failed = pyqtSignal(str)       # the error, already flattened
    run_overran = pyqtSignal()

    def __init__(self, window, nonai_enabled: Callable[[], bool], parent=None):
        super().__init__(parent)
        self._window = window
        self._nonai_enabled = nonai_enabled
        self._worker: PipelineWorker | None = None
        self._progress_popup: ProgressPopup | None = None
        self._watchdog = QTimer()
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def start(self, trigger: str) -> None:
        if self.is_running:
            return

        self.run_started.emit()
        self._worker = PipelineWorker(
            trigger=trigger, nonai_enabled=self._nonai_enabled(),
        )
        self._worker.pipeline_finished.connect(self._on_finished)
        self._worker.pipeline_error.connect(self._on_error)

        if self._window.isVisible():
            self._progress_popup = ProgressPopup(parent=self._window)
            self._worker.stage_started.connect(self._progress_popup.on_stage_started)
            self._worker.stage_completed.connect(self._progress_popup.on_stage_completed)
            self._worker.stage_progress.connect(self._progress_popup.on_stage_progress)
            self._progress_popup.show_over(self._window)

        self._worker.start()
        self._watchdog.start(config.PIPELINE_WALL_TIMEOUT_SECONDS * 1000)

    def wait_for_exit(self, msecs: int) -> None:
        """Give a run in flight *msecs* to finish its stage before the app goes."""
        if self.is_running:
            self._worker.wait(msecs)

    def _end_run(self) -> None:
        """Let go of what one run owned, whichever way it ended.

        The popup is one of them: it is closed by now, and held, the next run
        started while the window is hidden calls ``on_pipeline_finished()`` on
        last run's dead one.
        """
        self._watchdog.stop()
        if self._progress_popup is not None:
            self._progress_popup.on_pipeline_finished()
            self._progress_popup = None
        self.run_ended.emit()

    def _on_finished(self, record) -> None:
        self._end_run()
        self.run_finished.emit(record)

    def _on_error(self, message: str) -> None:
        self._end_run()
        self.run_failed.emit(message)
        log.error("Pipeline error: %s", message)

    def _on_watchdog(self) -> None:
        if not self.is_running:
            return  # Run finished just before the timer fired

        log.critical(
            "Watchdog fired: pipeline exceeded %d-second wall-clock limit; "
            "asking it to stop after the current stage",
            config.PIPELINE_WALL_TIMEOUT_SECONDS,
        )
        self._worker.requestInterruption()
        self.run_overran.emit()
