"""The wall-clock watchdog must tell the truth about an overrunning pipeline.

Nothing can hard-kill a stage that is mid-move without risking a half-moved
library, so when a run overruns the watchdog the run is genuinely still going.
Everything here pins the consequences: the worker stays the re-entry guard so
no second pipeline can start on top of the first, the scheduler and tray keep
showing a run in flight, and the pipeline is asked to stop cooperatively.
"""

import unittest
from unittest.mock import Mock, patch


from gui.settings import EvolverSettings
from tests.gui_support import build_evolver_app



class TestWatchdog(unittest.TestCase):

    def _app_mid_overrun(self, **settings_overrides):
        """An EvolverApp whose run has overrun the watchdog: the stubbed
        worker still reports isRunning() True when the timer fires."""
        settings = EvolverSettings(**settings_overrides)
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            app = build_evolver_app(self)

        worker = Mock()
        worker.isRunning.return_value = True
        patcher = patch("gui.app.PipelineWorker", return_value=worker)
        worker_cls = patcher.start()
        self.addCleanup(patcher.stop)

        app._start_run("scheduled")
        return app, worker, worker_cls

    def test_no_second_run_starts_while_the_overrun_pipeline_still_runs(self):
        """The audit's double-start: watchdog fires, next tick arrives, and a
        second pipeline must NOT start while the first still owns the library."""
        app, _worker, worker_cls = self._app_mid_overrun()

        app._on_watchdog()
        app._start_run("scheduled")

        self.assertEqual(worker_cls.call_count, 1)

    def test_the_watchdog_asks_the_pipeline_to_stop(self):
        """A hard kill could cut a stage mid-move, so the stop request is
        cooperative: the pipeline honors it between stages."""
        app, worker, _ = self._app_mid_overrun()

        app._on_watchdog()

        worker.requestInterruption.assert_called_once_with()

    def test_the_ui_keeps_showing_a_run_in_flight(self):
        """mark_idle()/set_running(False) here would re-enable Run Now and let
        the scheduler tick into a run that cannot start — the UI must keep
        saying what is true: a run is still in flight."""
        app, _, _ = self._app_mid_overrun()

        with patch.object(app._tray, "set_running") as set_running:
            app._on_watchdog()

        self.assertTrue(app._scheduler.is_running)
        set_running.assert_not_called()

    def test_the_toast_says_the_run_is_still_going_not_killed(self):
        """The old toast claimed "Pipeline killed" while nothing was killed."""
        app, _, _ = self._app_mid_overrun(enable_toasts=True)

        with patch.object(app._tray, "showMessage") as toast:
            app._on_watchdog()

        message = toast.call_args[0][1]
        self.assertIn("still running", message.lower())
        self.assertNotIn("killed", message.lower())

    def test_the_late_finish_still_reaches_its_teardown(self):
        """The overrun run does eventually end, and that ending is what
        re-opens scheduling — so its finished/error signals must stay wired."""
        app, worker, _ = self._app_mid_overrun()

        app._on_watchdog()

        worker.pipeline_finished.disconnect.assert_not_called()
        worker.pipeline_error.disconnect.assert_not_called()

    def test_a_run_that_actually_exited_reopens_the_gate(self):
        """The guard is the thread's liveness, not a latch: once the overrun
        worker really exits, the next tick may start a fresh run."""
        app, worker, worker_cls = self._app_mid_overrun()

        app._on_watchdog()
        worker.isRunning.return_value = False
        app._start_run("scheduled")

        self.assertEqual(worker_cls.call_count, 2)

    def test_a_run_that_finished_just_before_the_timer_is_left_alone(self):
        app, worker, _ = self._app_mid_overrun(enable_toasts=True)

        worker.isRunning.return_value = False
        with patch.object(app._tray, "showMessage") as toast:
            app._on_watchdog()

        worker.requestInterruption.assert_not_called()
        toast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
