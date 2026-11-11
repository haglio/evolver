from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEventLoop, QTimer
from shared_ui.testing import appending_to

from evolver import PipelineResult, StageRecord
from gui.worker import PipelineWorker
from util.run_lock import Busy


class TestPipelineWorker(unittest.TestCase):

    def _run_worker(self, pipeline_result=None, pipeline_error=None, trigger="manual",
                    progress_events=None):
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
                              on_stage_progress=None, nonai_enabled=None,
                              should_stop=None):
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
        worker.stage_started.connect(appending_to(started))
        worker.stage_completed.connect(lambda *args: completed.append(args))
        worker.pipeline_finished.connect(appending_to(finished))
        worker.pipeline_error.connect(appending_to(errors))
        worker.stage_progress.connect(lambda *args: progress.append(args))

        with patch("gui.worker.evolver.setup_logging"), \
             patch("gui.worker.evolver.check_dependencies"), \
             patch("gui.worker.evolver.run_pipeline", side_effect=fake_run_pipeline), \
             patch("gui.worker.save_run"), \
             patch("gui.worker.config"):
            worker.run()

        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

        return started, completed, finished, errors, progress

    def test_a_run_another_evolver_has_the_turn_for_says_why_it_did_not_start(self):
        with self.assertLogs("gui.worker", level="INFO") as logged:
            _, _, finished, errors, _ = self._run_worker(
                pipeline_error=Busy("another Evolver (process 42) is running the pipeline"))

        assert finished == []
        assert errors == ["another Evolver (process 42) is running the pipeline"]
        assert "Traceback" not in "\n".join(logged.output)

    def test_emits_stage_started_for_each_stage(self):
        started, _, _, _, _ = self._run_worker()
        assert started == ["sort", "upscale"]

    def test_emits_stage_completed_for_each_stage(self):
        _, completed, _, _, _ = self._run_worker()
        assert completed == [("sort",), ("upscale",)]

    def test_emits_pipeline_finished_with_run_record(self):
        _, _, finished, _, _ = self._run_worker()
        assert len(finished) == 1
        assert finished[0].trigger == "manual"
        assert finished[0].status == "success"

    def test_emits_pipeline_error_on_exception(self):
        _, _, _, errors, _ = self._run_worker(pipeline_error=RuntimeError("boom"))
        assert len(errors) == 1
        assert "boom" in errors[0]

    def test_the_traceback_is_logged_before_the_message_is_flattened(self):
        with self.assertLogs("gui.worker", level="ERROR") as caught:
            self._run_worker(pipeline_error=RuntimeError("boom"))

        assert any(record.exc_info for record in caught.records)

    def test_trigger_passed_to_run_record(self):
        _, _, finished, _, _ = self._run_worker(trigger="scheduled")
        assert finished[0].trigger == "scheduled"

    def test_emits_stage_progress_signal(self):
        events = [("upscale", 1, 3), ("upscale", 2, 3), ("upscale", 3, 3)]
        _, _, _, _, progress = self._run_worker(progress_events=events)
        assert len(progress) == 3
        assert progress[0] == ("upscale", 1, 3)
        assert progress[2] == ("upscale", 3, 3)

    def test_forwards_the_nonai_toggle_to_the_pipeline(self):
        worker = PipelineWorker(trigger="scheduled", nonai_enabled=True)
        with patch("gui.worker.evolver.setup_logging"), \
             patch("gui.worker.evolver.check_dependencies"), \
             patch("gui.worker.evolver.run_pipeline") as run_pipeline, \
             patch("gui.worker.RunRecord"), \
             patch("gui.worker.save_run"), \
             patch("gui.worker.config"):
            worker.run()
        assert run_pipeline.call_args.kwargs["nonai_enabled"]

    def test_hands_its_own_interruption_state_to_the_pipeline(self):
        worker = PipelineWorker(trigger="scheduled")
        with patch("gui.worker.evolver.setup_logging"), \
             patch("gui.worker.evolver.check_dependencies"), \
             patch("gui.worker.evolver.run_pipeline") as run_pipeline, \
             patch("gui.worker.RunRecord"), \
             patch("gui.worker.save_run"), \
             patch("gui.worker.config"):
            worker.run()
        should_stop = run_pipeline.call_args.kwargs["should_stop"]
        assert should_stop.__self__ is worker
        assert should_stop.__name__ == "isInterruptionRequested"


if __name__ == "__main__":
    unittest.main()
