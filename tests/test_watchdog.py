from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from gui.settings import EvolverSettings
from tests.gui_support import build_evolver_app


class TestWatchdog(unittest.TestCase):

    def _app_mid_overrun(self, **settings_overrides):
        settings = EvolverSettings(**settings_overrides)
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            app = build_evolver_app(self)

        worker = Mock()
        worker.isRunning.return_value = True
        patcher = patch("gui.run_controller.PipelineWorker", return_value=worker)
        worker_cls = patcher.start()
        self.addCleanup(patcher.stop)

        app._runs.start("scheduled")
        return app, worker, worker_cls

    def test_no_second_run_starts_while_the_overrun_pipeline_still_runs(self):
        app, _worker, worker_cls = self._app_mid_overrun()

        app._runs._on_watchdog()
        app._runs.start("scheduled")

        assert worker_cls.call_count == 1

    def test_the_watchdog_asks_the_pipeline_to_stop(self):
        app, worker, _ = self._app_mid_overrun()

        app._runs._on_watchdog()

        worker.requestInterruption.assert_called_once_with()

    def test_the_ui_keeps_showing_a_run_in_flight(self):
        app, _, _ = self._app_mid_overrun()

        with patch.object(app._tray, "show_schedule") as shown:
            app._runs._on_watchdog()

        assert app._scheduler.is_running
        assert app._tray.toolTip().endswith("Running...")
        shown.assert_not_called()

    def test_the_toast_says_the_run_is_still_going_not_killed(self):
        app, _, _ = self._app_mid_overrun(enable_toasts=True)

        with patch.object(app._tray, "showMessage") as toast:
            app._runs._on_watchdog()

        message = toast.call_args[0][1]
        assert "still running" in message.lower()
        assert "killed" not in message.lower()

    def test_the_late_finish_still_reaches_its_teardown(self):
        app, worker, _ = self._app_mid_overrun()

        app._runs._on_watchdog()

        worker.pipeline_finished.disconnect.assert_not_called()
        worker.pipeline_error.disconnect.assert_not_called()

    def test_a_run_that_actually_exited_reopens_the_gate(self):
        app, worker, worker_cls = self._app_mid_overrun()

        app._runs._on_watchdog()
        worker.isRunning.return_value = False
        app._runs.start("scheduled")

        assert worker_cls.call_count == 2

    def test_a_run_that_finished_just_before_the_timer_is_left_alone(self):
        app, worker, _ = self._app_mid_overrun(enable_toasts=True)

        worker.isRunning.return_value = False
        with patch.object(app._tray, "showMessage") as toast:
            app._runs._on_watchdog()

        worker.requestInterruption.assert_not_called()
        toast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
