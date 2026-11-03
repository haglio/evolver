
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

import config
import evolver
from gui.run_record import RunRecord, save_run
from util.run_lock import Busy

log = logging.getLogger(__name__)


class PipelineWorker(QThread):

    stage_started = pyqtSignal(str)
    stage_completed = pyqtSignal(str)
    stage_progress = pyqtSignal(str, int, int)
    pipeline_finished = pyqtSignal(object)
    pipeline_error = pyqtSignal(str)

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
                should_stop=self.isInterruptionRequested,
            )
            record = RunRecord.from_pipeline_result(result, trigger=self._trigger)
            try:
                save_run(record, config.RUNS_DIR)
            except Exception:
                log.exception("Failed to save run record")
            self.pipeline_finished.emit(record)
        except Busy as busy:
            log.info("Pipeline run not started: %s", busy)
            self.pipeline_error.emit(str(busy))
        except Exception as exc:
            log.exception("Pipeline run failed")
            self.pipeline_error.emit(str(exc))

    def _on_stage_start(self, name: str):
        self.stage_started.emit(name)

    def _on_stage_complete(self, name: str, *_):
        self.stage_completed.emit(name)

    def _on_stage_progress(self, name: str, current: int, total: int):
        self.stage_progress.emit(name, current, total)
