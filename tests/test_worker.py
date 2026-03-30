import unittest
from unittest.mock import Mock, patch, MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer

from evolver import PipelineResult, StageRecord
from gui.worker import PipelineWorker

# QApplication must exist for signal/slot to work
_app = QApplication.instance() or QApplication([])


class TestPipelineWorker(unittest.TestCase):

    def _run_worker(self, pipeline_result=None, pipeline_error=None, trigger="manual",
                    progress_events=None):
        """Run a PipelineWorker with mocked pipeline, collect emitted signals.

        Args:
            progress_events: List of (name, current, total) tuples to emit via
                on_stage_progress during the fake pipeline run.
        """
        if pipeline_result is None and pipeline_error is None:
            pipeline_result = PipelineResult(
                stages=[
                    StageRecord("sort", "completed", 1.0, Mock(moved=2)),
                    StageRecord("upscale", "skipped", 0.0, skip_reason="cpu_busy"),
                ],
                has_errors=False,
                duration_seconds=5.0,
            )

        started = []
        completed = []
        finished = []
        errors = []
        progress = []

        def fake_run_pipeline(on_stage_start=None, on_stage_complete=None,
                              on_stage_progress=None):
            if pipeline_error:
                raise pipeline_error
            for sr in pipeline_result.stages:
                if on_stage_start:
                    on_stage_start(sr.name)
                if on_stage_complete:
                    on_stage_complete(sr.name, sr.result, sr.duration_seconds, sr.status)
            if on_stage_progress and progress_events:
                for name, cur, tot in progress_events:
                    on_stage_progress(name, cur, tot)
            return pipeline_result

        worker = PipelineWorker(trigger=trigger)
        worker.stage_started.connect(lambda name: started.append(name))
        worker.stage_completed.connect(lambda *args: completed.append(args))
        worker.pipeline_finished.connect(lambda rec: finished.append(rec))
        worker.pipeline_error.connect(lambda msg: errors.append(msg))
        worker.stage_progress.connect(lambda *args: progress.append(args))

        with patch("gui.worker.evolver.setup_logging"), \
             patch("gui.worker.evolver.check_dependencies"), \
             patch("gui.worker.evolver.run_pipeline", side_effect=fake_run_pipeline), \
             patch("gui.worker.save_run"), \
             patch("gui.worker.config"):
            worker.run()

        # Process pending signals
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

        return started, completed, finished, errors, progress

    def test_emits_stage_started_for_each_stage(self):
        started, _, _, _, _ = self._run_worker()
        self.assertEqual(started, ["sort", "upscale"])

    def test_emits_stage_completed_for_each_stage(self):
        _, completed, _, _, _ = self._run_worker()
        self.assertEqual(len(completed), 2)
        self.assertEqual(completed[0][0], "sort")
        self.assertEqual(completed[0][3], "completed")
        self.assertEqual(completed[1][0], "upscale")
        self.assertEqual(completed[1][3], "skipped")

    def test_emits_pipeline_finished_with_run_record(self):
        _, _, finished, _, _ = self._run_worker()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0].trigger, "manual")
        self.assertEqual(finished[0].status, "success")

    def test_emits_pipeline_error_on_exception(self):
        _, _, _, errors, _ = self._run_worker(pipeline_error=RuntimeError("boom"))
        self.assertEqual(len(errors), 1)
        self.assertIn("boom", errors[0])

    def test_trigger_passed_to_run_record(self):
        _, _, finished, _, _ = self._run_worker(trigger="scheduled")
        self.assertEqual(finished[0].trigger, "scheduled")

    def test_emits_stage_progress_signal(self):
        events = [("upscale", 1, 3), ("upscale", 2, 3), ("upscale", 3, 3)]
        _, _, _, _, progress = self._run_worker(progress_events=events)
        self.assertEqual(len(progress), 3)
        self.assertEqual(progress[0], ("upscale", 1, 3))
        self.assertEqual(progress[2], ("upscale", 3, 3))


if __name__ == "__main__":
    unittest.main()
