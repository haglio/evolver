from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from app_support.testing import start_again_stand_in, update_waiting_for
from PyQt6.QtCore import QEvent

import config
from gui import single_instance
from gui.app import _wire
from gui.run_history import RunHistory
from gui.run_record import RunRecord
from gui.settings import EvolverSettings
from gui.single_instance import Outcome
from tests.gui_support import EMPTY_QUEUE, QAPP, DoneAtOnce, build_evolver_app, retire_evolver_app
from tests.temp_helpers import make_run_record, override_config


class TestAppStartup:

    def test_evolver_app_constructs_without_error(self, request):
        app = build_evolver_app(request)
        assert app._tray is not None
        assert app._window is not None
        assert app._scheduler is not None


class TestRetiringAnApp:
    def test_its_windows_are_gone_when_the_teardown_returns(self):
        app = build_evolver_app(SimpleNamespace(addfinalizer=lambda _finalizer: None))
        with patch("gui.app.run_log.read_run", return_value=""):
            app._show_run_log(make_run_record())
        windows = {app._window, app._log_window}

        retire_evolver_app(app)

        assert windows.isdisjoint(QAPP.topLevelWidgets())


class TestBuildingIsNotStarting:
    def test_construction_claims_no_identity(self, request):
        with patch("gui.app.process_identity.claim") as claim:
            build_evolver_app(request)
        claim.assert_not_called()

    def test_construction_starts_neither_timer(self, request):
        app = build_evolver_app(request)
        assert not app._presence.is_running
        assert not app._runs._watchdog.isActive()

    def test_construction_reads_no_run_history(self, request):
        with patch("gui.main_window.newest_runs") as load:
            build_evolver_app(request)
        load.assert_not_called()

    def test_starting_does_all_four(self, request):
        app = build_evolver_app(request)
        with patch("gui.app.process_identity.claim") as claim, \
             patch("gui.main_window.newest_runs", return_value=[]) as load:
            app.start()

        claim.assert_called_once_with(app._app)
        load.assert_called_once()
        assert app._presence.is_running
        assert app._scheduler.next_run_at is not None


class TestCommandWiring:

    def test_a_command_a_view_offers_with_no_slot_is_refused(self):
        view = SimpleNamespace(commands=lambda: {"run_now": MagicMock(), "quit": MagicMock()})

        with pytest.raises(ValueError, match="quit"):
            _wire(view, {"run_now": lambda: None})

    def test_a_slot_no_view_offers_is_refused_too(self):
        view = SimpleNamespace(commands=lambda: {"run_now": MagicMock()})

        with pytest.raises(ValueError, match="backfill"):
            _wire(view, {"run_now": lambda: None, "backfill": lambda: None})

    def test_each_command_reaches_its_own_slot(self):
        signals = {"run_now": MagicMock(), "quit": MagicMock()}
        slots = {"run_now": object(), "quit": object()}

        _wire(SimpleNamespace(commands=lambda: signals), slots)

        signals["run_now"].connect.assert_called_once_with(slots["run_now"])
        signals["quit"].connect.assert_called_once_with(slots["quit"])

    def test_the_two_views_name_their_shared_commands_the_same(self, request):
        app = build_evolver_app(request)

        assert set(app._window.commands()) < set(app._tray.commands())


class TestRunTeardown:
    def _finished_record(self, status="success"):
        record = MagicMock()
        record.status = status
        record.duration_seconds = 12.0
        return record

    def test_a_finished_run_lets_go_of_its_progress_popup(self, request):
        app = build_evolver_app(request)
        popup = MagicMock()
        app._runs._progress_popup = popup

        app._runs._on_finished(self._finished_record())

        popup.on_pipeline_finished.assert_called_once_with()
        assert app._runs._progress_popup is None

    def test_an_errored_run_lets_go_of_it_too(self, request):
        app = build_evolver_app(request)
        popup = MagicMock()
        app._runs._progress_popup = popup

        app._runs._on_error("something went wrong")

        popup.on_pipeline_finished.assert_called_once_with()
        assert app._runs._progress_popup is None

    def test_a_finished_run_stops_the_watchdog_and_re_opens_scheduling(self, request):
        app = build_evolver_app(request)
        with patch("gui.run_controller.PipelineWorker"):
            app._runs.start("manual")
        assert app._runs._watchdog.isActive()

        app._runs._on_finished(self._finished_record())

        assert not app._runs._watchdog.isActive()
        assert not app._scheduler.is_running

    def test_an_errored_run_does_the_same(self, request):
        app = build_evolver_app(request)
        with patch("gui.run_controller.PipelineWorker"):
            app._runs.start("manual")

        app._runs._on_error("something went wrong")

        assert not app._runs._watchdog.isActive()
        assert not app._scheduler.is_running


class TestToastPolicy:
    def _app(self, request, *, enable_toasts):
        settings = EvolverSettings(enable_toasts=enable_toasts)
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            return build_evolver_app(request)

    def _record(self, status="success"):
        record = MagicMock()
        record.status = status
        record.duration_seconds = 12.0
        return record

    def test_toasts_off_silences_the_finish_the_error_and_the_overrun(self, request):
        app = self._app(request, enable_toasts=False)
        with patch("gui.run_controller.PipelineWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            app._runs.start("manual")

        with patch.object(app._tray, "showMessage") as toast:
            app._runs._on_watchdog()
            app._runs._on_error("boom")
            app._runs._on_finished(self._record())

        toast.assert_not_called()

    def test_toasts_on_says_something_for_each_of_the_three(self, request):
        app = self._app(request, enable_toasts=True)
        with patch("gui.run_controller.PipelineWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            app._runs.start("manual")

        with patch.object(app._tray, "showMessage") as toast:
            app._runs._on_watchdog()
            app._runs._on_error("boom")
            app._runs._on_finished(self._record())

        assert toast.call_count == 3


class TestTopazSignInNotice:
    def test_a_finished_run_held_back_for_the_topaz_sign_in_tells_the_user(self, request):
        app = build_evolver_app(request)
        record = RunRecord(
            id="r", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:00:10",
            duration_seconds=10.0, trigger="scheduled", status="success",
            stages=[{"name": "upscale", "status": "skipped", "duration_seconds": 0.0,
                     "result": None, "skip_reason": "topaz_sign_in_expired"}],
        )

        with patch("gui.sign_in_notice.show_error") as show_error:
            app._on_finished(record)

        show_error.assert_called_once()


class TestStatsWindowLifetime:
    def test_the_window_opens_at_once_and_the_run_history_is_read_off_its_thread(
            self, request):
        app = build_evolver_app(request)
        app._background = MagicMock()

        with patch("gui.run_history.RunHistory.read", return_value=RunHistory.of([])) as read:
            app._show_stats()
            read.assert_not_called()
            assert app._stats.current.isVisible()
            work, then = (app._background.run.call_args.args[0],
                          app._background.run.call_args.kwargs["then"])
            then(work())

        read.assert_called_once_with(config.RUNS_DIR)
        assert app._stats.current._placeholder.text() == "No run data available."

    def test_a_history_read_for_a_window_since_closed_and_gone_is_let_go(self, request):
        app = build_evolver_app(request)
        app._background = MagicMock()
        app._show_stats()
        answer_for_the_first = app._background.run.call_args.kwargs["then"]
        app._stats.current.close()
        app._show_stats()
        QAPP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        answer_for_the_first(RunHistory.of([make_run_record()]))

        assert app._stats.current._chart is None

    def test_a_second_stats_window_takes_the_first_one_down(self, request):
        app = build_evolver_app(request)
        app._background = MagicMock()
        with patch("gui.app.StatsWindow") as stats_cls:
            first = stats_cls.return_value
            first.isVisible.return_value = False
            app._show_stats()
            app._show_stats()

        first.close.assert_called_once_with()
        first.deleteLater.assert_called_once_with()

    def test_a_stats_window_still_open_is_raised_rather_than_replaced(self, request):
        app = build_evolver_app(request)
        app._background = MagicMock()
        with patch("gui.app.StatsWindow") as stats_cls:
            stats_cls.return_value.isVisible.return_value = True
            app._show_stats()
            app._show_stats()

        assert stats_cls.call_count == 1
        stats_cls.return_value.raise_.assert_called_once_with()
        stats_cls.return_value.close.assert_not_called()


class TestOneRunAfterAnother:
    def _started(self, app, worker_cls):
        return worker_cls.call_count

    def test_with_nothing_running_it_starts_at_once(self, request):
        app = build_evolver_app(request)
        with patch("gui.run_controller.PipelineWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = False
            app._runs.start_when_free("manual")
        assert worker_cls.call_count == 1

    def test_mid_run_it_waits_for_the_thread_to_let_go(self, request):
        app = build_evolver_app(request)
        with patch("gui.run_controller.PipelineWorker") as worker_cls:
            worker = worker_cls.return_value
            worker.isRunning.return_value = True
            app._runs.start("scheduled")

            app._runs.start_when_free("manual")
            assert worker_cls.call_count == 1

            worker.isRunning.return_value = False
            worker.finished.connect.call_args.args[0]()
            assert worker_cls.call_count == 2
            assert worker_cls.call_args.kwargs["trigger"] == "manual"

    def test_a_run_nobody_asked_to_follow_is_not_started_again(self, request):
        app = build_evolver_app(request)
        with patch("gui.run_controller.PipelineWorker") as worker_cls:
            worker = worker_cls.return_value
            worker.isRunning.return_value = True
            app._runs.start("scheduled")

            worker.isRunning.return_value = False
            worker.finished.connect.call_args.args[0]()
        assert worker_cls.call_count == 1


class TestTheUpscaleQueueWindowsWiring:
    def _opened(self, request):
        with patch("gui.app.BackgroundQueue", DoneAtOnce):
            app = build_evolver_app(request)
        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE):
            app._tray.queue_action.trigger()
        return app

    def test_the_queue_command_opens_the_queue_window(self, request):
        app = self._opened(request)

        assert app._queue.is_on_screen

    def test_a_video_asked_for_now_starts_a_run_through_the_run_controller(self, request):
        app = self._opened(request)

        with patch("evolver.upscale_now"), \
             patch("evolver.upscale_queue", return_value=EMPTY_QUEUE), \
             patch("gui.run_controller.PipelineWorker") as worker_cls:
            app._queue._window.current.now_requested.emit("lagoon/0 unsorted/a.mp4")

        assert worker_cls.call_args.kwargs["trigger"] == "manual"

    def test_withdrawing_the_ask_parks_the_encode_through_the_presence_poll(self, request):
        app = self._opened(request)
        app._settings.nonai_upscale_enabled = True

        with patch("evolver.withdraw_upscale_now"), \
             patch("evolver.upscale_queue", return_value=EMPTY_QUEUE), \
             patch("evolver.throttle_nonai_to_presence") as parked:
            app._queue._window.current.now_withdrawn.emit()

        parked.assert_called_once_with()

    def test_a_finished_run_redraws_it(self, request):
        app = self._opened(request)

        with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE) as queue, \
             patch("gui.main_window.newest_runs", return_value=[]):
            app._runs.run_ended.emit()

        queue.assert_called_once_with()


class TestNonAiUpscaleToggle:

    def _app_with_fresh_settings(self, request):
        with patch("gui.app.EvolverSettings.load", return_value=EvolverSettings()):
            return build_evolver_app(request)

    def test_the_trays_switch_starts_off_by_default(self, request):
        app = self._app_with_fresh_settings(request)
        assert not app._tray.nonai_switch.isChecked()

    def test_toggling_flips_and_saves_the_setting(self, request):
        app = self._app_with_fresh_settings(request)
        with patch("gui.app.EvolverSettings.save") as mock_save:
            app._tray.nonai_action.trigger()
        assert app._settings.nonai_upscale_enabled
        mock_save.assert_called_once()

    def test_the_toolbars_switch_flips_and_saves_the_setting_too(self, request):
        app = self._app_with_fresh_settings(request)
        with patch("gui.app.EvolverSettings.save") as mock_save:
            app._window.nonai_switch.click()
        assert app._settings.nonai_upscale_enabled
        mock_save.assert_called_once()

    def test_switching_it_on_in_the_toolbar_checks_it_in_the_tray_menu(self, request):
        app = self._app_with_fresh_settings(request)
        with patch("gui.app.EvolverSettings.save"):
            app._window.nonai_switch.click()
        assert app._tray.nonai_switch.isChecked()

    def test_checking_it_in_the_tray_menu_switches_it_on_in_the_toolbar(self, request):
        app = self._app_with_fresh_settings(request)
        with patch("gui.app.EvolverSettings.save"):
            app._tray.nonai_action.trigger()
        assert app._window.nonai_switch.isChecked()

    def test_a_saved_opt_in_starts_on_in_the_tray_menu_and_the_toolbar(self, request):
        settings = EvolverSettings()
        settings.nonai_upscale_enabled = True
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            app = build_evolver_app(request)
        assert app._tray.nonai_switch.isChecked()
        assert app._window.nonai_switch.isChecked()

    def test_worker_receives_the_toggle_state(self, request):
        app = self._app_with_fresh_settings(request)
        app._settings.nonai_upscale_enabled = True
        with patch("gui.run_controller.PipelineWorker") as mock_worker:
            app._runs.start("manual")
        assert mock_worker.call_args.kwargs["nonai_enabled"]


class TestPresenceMonitor:
    def _app_with_toggle(self, request, enabled):
        settings = EvolverSettings()
        settings.nonai_upscale_enabled = enabled
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            return build_evolver_app(request)

    def test_monitor_timer_runs_once_the_app_is_started(self, request):
        app = self._app_with_toggle(request, True)
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.newest_runs", return_value=[]):
            app.start()
        assert app._presence.is_running

    def test_throttles_the_encode_while_the_toggle_is_on(self, request):
        app = self._app_with_toggle(request, True)
        with patch("evolver.throttle_nonai_to_presence") as mock_throttle:
            app._presence.poll()
        mock_throttle.assert_called_once_with()

    def test_leaves_the_encode_alone_while_the_toggle_is_off(self, request):
        app = self._app_with_toggle(request, False)
        with patch("evolver.throttle_nonai_to_presence") as mock_throttle:
            app._presence.poll()
        mock_throttle.assert_not_called()

    def test_the_toggle_is_read_at_every_poll_not_at_construction(self, request):
        app = self._app_with_toggle(request, False)
        app._settings.nonai_upscale_enabled = True

        with patch("evolver.throttle_nonai_to_presence") as mock_throttle:
            app._presence.poll()

        mock_throttle.assert_called_once_with()


class TestSessionManagement:

    def test_connects_to_commit_data_request(self, request):
        app = build_evolver_app(request)
        try:
            app._app.commitDataRequest.disconnect(app._on_session_end)
        except TypeError:
            raise AssertionError(
                "commitDataRequest is not connected to _on_session_end"
            ) from None
        app._app.commitDataRequest.connect(app._on_session_end)

    def test_session_end_logs_to_crash_log(self, request):
        app = build_evolver_app(request)

        mock_manager = MagicMock()
        with patch("gui.app.crash_log.write_info") as mock_write:
            app._on_session_end(mock_manager)

        mock_write.assert_called_once()
        header = mock_write.call_args[0][0]
        assert "session" in header.lower()

    def test_session_end_quits_app(self, request):
        app = build_evolver_app(request)

        mock_manager = MagicMock()
        with patch.object(app, "_shutdown") as mock_quit, \
             patch("gui.app.crash_log.write_info"):
            app._on_session_end(mock_manager)

        mock_quit.assert_called_once()


class TestRestart:
    def _restarted(self, request, *, window_visible=False, branch_session=False):
        app = build_evolver_app(request)
        app._session.is_preview = branch_session
        with update_waiting_for(config.PROJECT_DIR), \
             start_again_stand_in() as start_again, \
             patch.object(app, "_shutdown") as quit_this_copy, \
             patch.object(app._window, "isVisible", return_value=window_visible), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as allow:
            app._restart()
        return start_again, quit_this_copy, allow

    def test_the_next_copy_starts_through_the_launcher_after_this_one_has_quit(self, request):
        start_again, quit_this_copy, _ = self._restarted(request)

        start_again.assert_called_once_with(os.getpid(), config.PROJECT_DIR / "launch_evolver.vbs")
        quit_this_copy.assert_called_once()

    def test_a_restart_from_the_window_comes_back_showing_it(self, request):
        start_again, _, allow = self._restarted(request, window_visible=True)

        start_again.assert_called_once_with(
            os.getpid(), config.PROJECT_DIR / "launch_evolver_showing_its_window.vbs")
        allow.assert_called_once_with(-1)

    def test_a_restart_from_the_tray_leaves_the_foreground_alone(self, request):
        _, _, allow = self._restarted(request)

        allow.assert_not_called()

    def test_a_preview_restarts_as_the_preview_it_is(self, request):
        start_again, _, _ = self._restarted(request, branch_session=True)

        start_again.assert_called_once_with(os.getpid(), config.PROJECT_DIR / "launch_preview_branch.vbs")


def _the_main_window(app):
    app._show_window()


def _the_stats_window(app):
    with patch("gui.run_history.RunHistory.read", return_value=RunHistory.of([])):
        app._show_stats()


def _the_queue_window(app):
    with patch("evolver.upscale_queue", return_value=EMPTY_QUEUE):
        app._queue.show()


def _the_log_window(app):
    with patch("gui.app.run_log.read_run", return_value=""):
        app._show_run_log(make_run_record())


class TestTakingAnUpdate:
    def _ticked(self, request, *, branch_session=False, running=False, open_window=None):
        with patch("gui.app.BackgroundQueue", DoneAtOnce):
            app = build_evolver_app(request)
        app._session.is_preview = branch_session
        if open_window is not None:
            open_window(app)
        with update_waiting_for(config.PROJECT_DIR), \
             start_again_stand_in() as start_again, \
             patch.object(app, "_shutdown") as quit_this_copy, \
             patch.object(type(app._runs), "is_running", new=running):
            app._updates.tick()
        return start_again, quit_this_copy

    def test_an_update_waiting_for_evolver_starts_it_again_through_its_launcher(self, request, monkeypatch):
        start_again, quit_this_copy = self._ticked(request)

        start_again.assert_called_once_with(os.getpid(), config.PROJECT_DIR / "launch_evolver.vbs")
        quit_this_copy.assert_called_once()

    def test_an_update_waits_for_the_run_going_to_end(self, request, monkeypatch):
        start_again, quit_this_copy = self._ticked(request, running=True)

        start_again.assert_not_called()
        quit_this_copy.assert_not_called()

    @pytest.mark.parametrize("open_window", [_the_main_window, _the_stats_window,
                                             _the_queue_window, _the_log_window])
    def test_an_update_waits_while_a_window_of_evolver_is_on_screen(self, request, monkeypatch, open_window):
        start_again, quit_this_copy = self._ticked(request, open_window=open_window)

        start_again.assert_not_called()
        quit_this_copy.assert_not_called()

    def test_a_preview_never_starts_again_for_an_update(self, request, monkeypatch):
        start_again, quit_this_copy = self._ticked(request, branch_session=True)

        start_again.assert_not_called()
        quit_this_copy.assert_not_called()

    def test_the_running_evolver_looks_for_an_update_every_minute(self, request):
        with patch("gui.app.production_update.UpdateWatch.tick") as looked:
            app = build_evolver_app(request)

            with patch.object(app._peer, "tick"), patch("gui.app.process_identity.claim"):
                app.start()
                app._update_timer.timeout.emit()

        assert app._update_timer.isActive()
        assert app._update_timer.interval() == 60_000
        looked.assert_called_once()

    def test_shutting_down_stops_looking_for_an_update(self, request):
        app = build_evolver_app(request)

        with patch.object(app._peer, "tick"), patch("gui.app.process_identity.claim"):
            app.start()
        with patch.object(app._app, "quit"):
            app._shutdown()

        assert not app._update_timer.isActive()


class TestALaunchThatFindsEvolverUp:
    def _launch(self, request, outcome, *, preview=False):
        with override_config(BRANCH_SESSION=preview):
            app = build_evolver_app(request)

        launch = SimpleNamespace(order=Mock())
        with patch.object(app._instance, "become_evolver", return_value=outcome) as launch.became, \
             patch.object(app._instance, "serve_launches"), \
             patch("gui.app.process_identity.claim") as claim, \
             patch("gui.app.show_error") as launch.alert:
            launch.order.attach_mock(claim, "claim")
            launch.order.attach_mock(launch.alert, "alert")
            launch.exit_code = app.run()

        return launch

    def test_the_usual_evolver_launches_as_the_usual_one(self, request):
        launch = self._launch(request, Outcome.HANDED_OFF)

        launch.became.assert_called_once_with(as_preview=False, only_if_not_running=False)

    def test_a_preview_launches_as_a_preview(self, request):
        launch = self._launch(request, Outcome.HANDED_OFF, preview=True)

        launch.became.assert_called_once_with(as_preview=True, only_if_not_running=False)

    def test_a_taken_handoff_exits_with_no_dialog(self, request):
        launch = self._launch(request, Outcome.HANDED_OFF)

        assert launch.exit_code == 0
        launch.alert.assert_not_called()

    def test_a_handoff_the_running_instance_never_answered_is_visible(self, request):
        launch = self._launch(request, Outcome.UNANSWERED)

        launch.alert.assert_called_once()
        assert "evolver" in " ".join(launch.alert.call_args[0]).lower()
        assert launch.exit_code == 0

    def test_what_a_launch_the_running_instance_never_answered_shows_is_evolver_on_the_taskbar(
            self, request):
        launch = self._launch(request, Outcome.UNANSWERED)

        assert [name for name, _args, _kwargs in launch.order.mock_calls] == ["claim", "alert"]


class TestAStartForWhenEvolverIsNotRunning:

    def _start(self, request, *, already_running):
        app = build_evolver_app(request)

        with patch.object(app._instance, "claim", return_value=not already_running), \
             patch.object(app._instance, "take_over") as take_over, \
             patch.object(app._instance, "serve_launches") as serve, \
             patch.object(app, "start") as start, \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.show_error"), \
             patch("util.crash_log.write_info"), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py", "--if-not-running"]
            exit_code = app.run()

        return SimpleNamespace(exit_code=exit_code, take_over=take_over, serve=serve, start=start)

    def test_an_evolver_already_running_is_left_as_it_was(self, request):
        started = self._start(request, already_running=True)

        started.take_over.assert_not_called()
        started.start.assert_not_called()
        assert started.exit_code == 0

    def test_with_none_running_it_is_evolver_without_claiming_twice(self, request):
        started = self._start(request, already_running=False)

        started.take_over.assert_not_called()
        started.serve.assert_called_once()
        started.start.assert_called_once_with()


class TestAnsweringLaunches:
    def _run_as_first_instance(self, request, *, preview=False):
        with override_config(BRANCH_SESSION=preview):
            app = build_evolver_app(request)

        with patch.object(app._instance, "take_over", return_value=Outcome.CLAIMED), \
             patch.object(app._instance, "serve_launches") as serve, \
             patch.object(app, "start"), \
             patch.object(app._app, "exec", return_value=0):
            app.run()

        return app, serve.call_args.kwargs

    def test_the_usual_evolver_opens_its_window_for_a_usual_launch(self, request):
        _, served = self._run_as_first_instance(request)

        assert not served["steps_aside_for"](single_instance.USUAL)
        assert not served["steps_aside_for"](b"")

    def test_the_usual_evolver_steps_aside_for_a_preview(self, request):
        _, served = self._run_as_first_instance(request)

        assert served["steps_aside_for"](single_instance.PREVIEW)

    def test_a_preview_steps_aside_for_the_usual_evolver_and_for_a_newer_preview(self, request):
        _, served = self._run_as_first_instance(request, preview=True)

        assert served["steps_aside_for"](single_instance.USUAL)
        assert served["steps_aside_for"](single_instance.PREVIEW)

    def test_a_preview_opens_its_window_for_a_launcher_that_says_nothing(self, request):
        _, served = self._run_as_first_instance(request, preview=True)

        assert not served["steps_aside_for"](b"")

    def test_what_it_registered_opens_the_window(self, request):
        app, served = self._run_as_first_instance(request)

        with patch.object(app._window, "show") as mock_show, \
             patch.object(app._window, "raise_"), \
             patch.object(app._window, "activateWindow"):
            served["on_show"]()

        mock_show.assert_called_once()

    def test_stepping_aside_quits_without_standing_evolver_down(self, request):
        app, served = self._run_as_first_instance(request)

        with patch.object(app._app, "quit") as quit_the_application, \
             patch("gui.peer_watch.stand_evolver_down") as stood_down:
            served["on_step_aside"]()

        quit_the_application.assert_called_once_with()
        stood_down.assert_not_called()

    def test_an_evolver_on_its_way_out_answers_no_more_launches(self, request):
        app = build_evolver_app(request)

        with patch.object(app._instance, "stop_serving") as stop, \
             patch.object(app._app, "quit"):
            app._shutdown()

        stop.assert_called_once_with()


class TestShowWindowFlag:
    def test_run_shows_window_when_flag_present(self, request):
        app = build_evolver_app(request)

        with patch.object(app, "_show_window") as mock_show, \
             patch.object(app._instance, "take_over", return_value=Outcome.CLAIMED), \
             patch.object(app._instance, "serve_launches"), \
             patch("gui.app.process_identity.claim"), \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py", "--show-window"]
            app.run()
            mock_show.assert_called_once()

    def test_run_does_not_show_window_without_flag(self, request):
        app = build_evolver_app(request)

        with patch.object(app, "_show_window") as mock_show, \
             patch.object(app._instance, "take_over", return_value=Outcome.CLAIMED), \
             patch.object(app._instance, "serve_launches"), \
             patch("gui.app.process_identity.claim"), \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py"]
            app.run()
            mock_show.assert_not_called()
