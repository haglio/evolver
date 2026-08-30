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
    stage_completed = pyqtSignal(str)         # stage_name
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
                # The watchdog's requestInterruption() lands here: the pipeline
                # checks it between stages and drops the rest of the run.
                should_stop=self.isInterruptionRequested,
            )
            record = RunRecord.from_pipeline_result(result, trigger=self._trigger)
            try:
                save_run(record, config.RUNS_DIR)
            except Exception:
                log.exception("Failed to save run record")
            self.pipeline_finished.emit(record)
        except Exception as exc:
            # Logged before it is flattened: str(exc) is all the GUI ever sees,
            # so without this the only record of where a pipeline died is a
            # sentence in a toast.
            log.exception("Pipeline run failed")
            self.pipeline_error.emit(str(exc))

    def _on_stage_start(self, name: str):
        self.stage_started.emit(name)

    def _on_stage_complete(self, name: str, *_):
        # run_pipeline hands the callback the result, the elapsed time and the
        # status too; all three reach the run record by their own route, and
        # the only listener here marks a bar full.
        self.stage_completed.emit(name)

    def _on_stage_progress(self, name: str, current: int, total: int):
        self.stage_progress.emit(name, current, total)
