"""Background thread that runs the evolver pipeline and emits Qt signals."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

import config
import evolver
from gui.run_record import RunRecord, save_run

log = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """Runs evolver.run_pipeline() in a background thread.

    Signals are auto-queued across the thread boundary by Qt,
    so GUI slots receiving these signals run safely on the main thread.
    """

    stage_started = pyqtSignal(str)           # stage_name
    stage_completed = pyqtSignal(str, object, float, str)  # name, result, elapsed, status
    stage_progress = pyqtSignal(str, int, int)  # name, current, total
    pipeline_finished = pyqtSignal(object)    # RunRecord
    pipeline_error = pyqtSignal(str)          # error message

    def __init__(self, trigger: str = "scheduled", nonai_enabled: bool = False, parent=None):
        super().__init__(parent)
        self._trigger = trigger
        self._nonai_enabled = nonai_enabled

    def run(self):
        try:
            evolver.setup_logging()
            evolver.check_dependencies()
            result = evolver.run_pipeline(
                on_stage_start=self._on_stage_start,
                on_stage_complete=self._on_stage_complete,
                on_stage_progress=self._on_stage_progress,
                nonai_enabled=self._nonai_enabled,
            )
            record = RunRecord.from_pipeline_result(result, trigger=self._trigger)
            try:
                save_run(record, config.RUNS_DIR)
            except Exception:
                log.exception("Failed to save run record")
            self.pipeline_finished.emit(record)
        except Exception as exc:
            self.pipeline_error.emit(str(exc))

    def _on_stage_start(self, name: str):
        self.stage_started.emit(name)

    def _on_stage_complete(self, name: str, result: object, elapsed: float, status: str):
        self.stage_completed.emit(name, result, elapsed, status)

    def _on_stage_progress(self, name: str, current: int, total: int):
        self.stage_progress.emit(name, current, total)
