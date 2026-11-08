from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

import config
from gui.progress_popup import ProgressPopup
from gui.worker import PipelineWorker

log = logging.getLogger(__name__)

STAGE_GRACE_SECONDS = 5.0


class RunController(QObject):
    run_started = pyqtSignal()
    run_ended = pyqtSignal()
    run_finished = pyqtSignal(object)
    run_failed = pyqtSignal(str)
    run_overran = pyqtSignal()

    def __init__(self, window, nonai_enabled: Callable[[], bool], parent=None):
        super().__init__(parent)
        self._window = window
        self._nonai_enabled = nonai_enabled
        self._worker: PipelineWorker | None = None
        self._when_free = ""
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
        self._worker.finished.connect(self._start_what_was_waiting)

        if self._window.isVisible():
            self._progress_popup = ProgressPopup(parent=self._window)
            self._worker.stage_started.connect(self._progress_popup.on_stage_started)
            self._worker.stage_completed.connect(self._progress_popup.on_stage_completed)
            self._worker.stage_progress.connect(self._progress_popup.on_stage_progress)
            self._progress_popup.show_over(self._window)

        self._worker.start()
        self._watchdog.start(config.PIPELINE_WALL_TIMEOUT_SECONDS * 1000)

    def start_when_free(self, trigger: str) -> None:
        if self.is_running:
            self._when_free = trigger
        else:
            self.start(trigger)

    def _start_what_was_waiting(self) -> None:
        trigger, self._when_free = self._when_free, ""
        if trigger:
            self.start(trigger)

    def wait_for_exit(self) -> None:
        if self.is_running:
            self._worker.wait(int(STAGE_GRACE_SECONDS * 1000))

    def _end_run(self) -> None:
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
            return

        log.critical(
            "Watchdog fired: pipeline exceeded %d-second wall-clock limit; "
            "asking it to stop after the current stage",
            config.PIPELINE_WALL_TIMEOUT_SECONDS,
        )
        self._worker.requestInterruption()
        self.run_overran.emit()
