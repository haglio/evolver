"""Smoke test: verify the tray app can be constructed without crashing."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import config
from gui import single_instance
from gui.app import _wire
from gui.process_identity import APP_MODEL_ID
from gui.run_record import RunRecord
from gui.settings import EvolverSettings
from gui.single_instance import Outcome
from tests.gui_support import build_evolver_app
from tests.temp_helpers import override_config
from util.upscale_lineup import Lineup


class TestAppStartup:

    def test_evolver_app_constructs_without_error(self, request):
        app = build_evolver_app(request)
        # Tray, window, and scheduler should all exist
        assert app._tray is not None
        assert app._window is not None
        assert app._scheduler is not None

    def test_app_window_icon_matches_tray_icon(self, request):
        app = build_evolver_app(request)
        # Taskbar icon should be set to the same icon as the tray
        app_icon = app._app.windowIcon()
        assert not app_icon.isNull(), "Application window icon should be set"

    def test_app_sets_appusermodelid(self, request):
        app = build_evolver_app(request)
        with patch("gui.process_identity.set_app_user_model_id") as mock_set_id, \
             patch("gui.process_identity.set_taskbar_properties"):
            app.start()
        mock_set_id.assert_called_once_with(APP_MODEL_ID)


class TestBuildingIsNotStarting:
    """Constructing an EvolverApp touches nothing outside the process.

    It used to name this process to the shell, set taskbar properties on a
    window handle, read the whole run-history directory off disk and begin a
    twenty-second presence poll -- so a test that wanted any one part paid for
    all of them, and left a live timer running for the rest of the session.
    """

    def test_construction_claims_no_identity(self, request):
        with patch("gui.app.process_identity.claim") as claim:
            build_evolver_app(request)
        claim.assert_not_called()

    def test_construction_starts_neither_timer(self, request):
        app = build_evolver_app(request)
        assert not app._presence.is_running
        assert not app._runs._watchdog.isActive()

    def test_construction_reads_no_run_history(self, request):
        with patch("gui.main_window.load_runs") as load:
            build_evolver_app(request)
        load.assert_not_called()

    def test_starting_does_all_four(self, request):
        app = build_evolver_app(request)
        with patch("gui.app.process_identity.claim") as claim, \
             patch("gui.main_window.load_runs", return_value=[]) as load:
            app.start()

        claim.assert_called_once()
        load.assert_called_once()
        assert app._presence.is_running
        assert app._scheduler.next_run_at is not None


class TestCommandWiring:
    """Each view says what commands it offers; the app says what each one does.

    Ten tray attributes and six window ones used to be connected by hand, so
    every control was something two files had to agree about with nothing
    checking that they did -- and a QAction nobody connected raises nothing
    when clicked, it simply does not work.
    """

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
        """The toolbar is a subset of the tray menu. A name that drifted on one
        side would wire fine and just mean two different things."""
        app = build_evolver_app(request)

        assert set(app._window.commands()) < set(app._tray.commands())


class TestRunTeardown:
    """What ending a run has to let go of.

    The teardown was written out twice and the toast block three times, and
    both of the things they forgot are lifetime leaks that only show on the
    *second* run.
    """

    def _finished_record(self, status="success"):
        record = MagicMock()
        record.status = status
        record.duration_seconds = 12.0
        return record

    def test_a_finished_run_lets_go_of_its_progress_popup(self, request):
        """It is closed by then. Held, the next run started while the window is
        hidden calls on_pipeline_finished() on last run's dead popup."""
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
    """One place decides whether a tray balloon is shown at all."""

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
    def test_a_second_stats_window_takes_the_first_one_down(self, request):
        """The dialog is parented to the main window, so one replaced without
        being closed stays alive for the process's whole life."""
        app = build_evolver_app(request)
        with patch("gui.app.StatsWindow") as stats_cls, \
             patch("gui.app.load_runs", return_value=[]):
            first = stats_cls.return_value
            first.isVisible.return_value = False
            app._show_stats()
            app._show_stats()

        first.close.assert_called_once_with()
        first.deleteLater.assert_called_once_with()

    def test_a_stats_window_still_open_is_raised_rather_than_replaced(self, request):
        app = build_evolver_app(request)
        with patch("gui.app.StatsWindow") as stats_cls, \
             patch("gui.app.load_runs", return_value=[]):
            stats_cls.return_value.isVisible.return_value = True
            app._show_stats()
            app._show_stats()

        assert stats_cls.call_count == 1
        stats_cls.return_value.raise_.assert_called_once_with()
        stats_cls.return_value.close.assert_not_called()


class TestOneRunAfterAnother:
    """A request cannot wait for the next tick, so the run that answers it
    follows the one in flight rather than being dropped by the re-entry guard."""

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

            # What the thread's own finished signal reaches, once it has.
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


EMPTY_QUEUE = Lineup(rows=(), head=None)


class DoneAtOnce:
    """The app's background queue, doing each piece of work as it is handed over.

    So the patches a test stands up are still standing when the work runs.
    """

    def run(self, work, then=None):
        answer = work()
        if then is not None:
            then(answer)

    def stop(self):
        pass


class TestUpscaleQueueWindow:
    """The window that shows the upscale queue, and the verbs it offers."""

    def _open(self, app):
        app._background = DoneAtOnce()
        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            app._show_queue()
        return lineup

    def test_the_queue_is_read_off_the_windows_thread(self, request):
        """A run holding the stage, or a slow library drive, must not stop
        the window answering the mouse."""
        app = build_evolver_app(request)
        app._background = MagicMock()

        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            app._show_queue()
            lineup.assert_not_called()
            work, then = app._background.run.call_args.args[0], \
                app._background.run.call_args.kwargs["then"]
            then(work())

        lineup.assert_called_once_with()
        assert app._queue_window._heading.text() == "Nothing is waiting to be upscaled"

    def test_opening_it_hands_it_the_queue_as_it_stands(self, request):
        app = build_evolver_app(request)
        lineup = self._open(app)
        lineup.assert_called_once_with()
        assert app._queue_window.isVisible()

    def test_a_second_open_raises_the_one_already_up(self, request):
        app = build_evolver_app(request)
        self._open(app)
        first = app._queue_window
        self._open(app)
        assert app._queue_window is first

    def test_rearranging_it_pins_the_order_through_the_pipeline_module(self, request):
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.arrange_upscale_queue") as arranged:
            app._queue_window.arranged.emit(["larkin/0 unsorted/a.mp4"])
        arranged.assert_called_once_with(["larkin/0 unsorted/a.mp4"])

    def test_a_video_put_first_goes_first_and_starts_no_run(self, request):
        """Dragging a video to the top is ordering, not asking: it waits for
        the usual moment like any other."""
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.upscale_next") as put_first, \
             patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup, \
             patch.object(app._runs, "start_when_free") as run:
            app._queue_window.placed_first.emit("larkin/0 unsorted/a.mp4")
        put_first.assert_called_once_with("larkin/0 unsorted/a.mp4")
        asked.assert_not_called()
        run.assert_not_called()
        lineup.assert_called_once_with()

    def test_asking_for_one_now_records_it_and_runs_the_pipeline_at_once(self, request):
        """The stage starts encodes on a run and nowhere else, so asking for
        one has to bring the next run forward rather than wait ten minutes."""
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.upscale_now") as asked, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE), \
             patch.object(app._runs, "start_when_free") as run:
            app._queue_window.now_requested.emit("larkin/0 unsorted/a.mp4")
        asked.assert_called_once_with("larkin/0 unsorted/a.mp4")
        run.assert_called_once_with("manual")

    def test_withdrawing_the_ask_parks_the_encode_for_your_presence_again(self, request):
        """The poll that parks it fires every twenty seconds; the click that
        hands it back should not wait them out."""
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.withdraw_upscale_now") as withdrawn, \
             patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup, \
             patch.object(app._presence, "poll") as poll:
            app._queue_window.now_withdrawn.emit()
        withdrawn.assert_called_once_with()
        poll.assert_called_once_with()
        lineup.assert_called_once_with()

    def test_a_finished_run_redraws_it(self, request):
        """A run is what starts, promotes and fails encodes, so the window is
        stale the moment one ends."""
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup, \
             patch("gui.main_window.load_runs", return_value=[]):
            app._on_run_ended()
        lineup.assert_called_once_with()

    def test_it_asks_to_be_redrawn_while_it_is_open(self, request):
        """Presence parks and thaws the encode between runs, and the percent
        climbs the whole time."""
        app = build_evolver_app(request)
        self._open(app)
        with patch("evolver.upscale_lineup", return_value=EMPTY_QUEUE) as lineup:
            app._queue_window.refresh_wanted.emit()
        lineup.assert_called_once_with()


class TestNonAiUpscaleToggle:
    """The tray menu's opt-in switch for the multi-hour non-AI encodes."""

    def _app_with_fresh_settings(self, request):
        with patch("gui.app.EvolverSettings.load", return_value=EvolverSettings()):
            return build_evolver_app(request)

    def test_tray_toggle_starts_unchecked_by_default(self, request):
        app = self._app_with_fresh_settings(request)
        assert app._tray.nonai_action.isCheckable()
        assert not app._tray.nonai_action.isChecked()

    def test_toggling_flips_and_saves_the_setting(self, request):
        app = self._app_with_fresh_settings(request)
        with patch("gui.app.EvolverSettings.save") as mock_save:
            app._tray.nonai_action.trigger()
        assert app._settings.nonai_upscale_enabled
        mock_save.assert_called_once()

    def test_worker_receives_the_toggle_state(self, request):
        app = self._app_with_fresh_settings(request)
        app._settings.nonai_upscale_enabled = True
        with patch("gui.run_controller.PipelineWorker") as mock_worker:
            app._runs.start("manual")
        assert mock_worker.call_args.kwargs["nonai_enabled"]


class TestPresenceMonitor:
    """A fast timer keeps the in-flight encode in step with the user between
    the slow pipeline ticks."""

    def _app_with_toggle(self, request, enabled):
        settings = EvolverSettings()
        settings.nonai_upscale_enabled = enabled
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            return build_evolver_app(request)

    def test_monitor_timer_runs_once_the_app_is_started(self, request):
        app = self._app_with_toggle(request, True)
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.load_runs", return_value=[]):
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
        """The tray flips it while this is running, so a throttle that had to
        be rebuilt to notice would be a second place the setting lives."""
        app = self._app_with_toggle(request, False)
        app._settings.nonai_upscale_enabled = True

        with patch("evolver.throttle_nonai_to_presence") as mock_throttle:
            app._presence.poll()

        mock_throttle.assert_called_once_with()


class TestSessionManagement:
    """EvolverApp must log Windows session-management events that could kill it."""

    def test_connects_to_commit_data_request(self, request):
        """The session-end handler is wired to the signal, not merely defined.

        This used to assert ``hasattr(app, "_on_session_end")``, which stays
        true with the connect line deleted — and then Windows shutdown
        force-kills the tray with a pipeline still running. The signal
        cannot be emitted from a test (QSessionManager is not constructible),
        so pin the connection itself: disconnect names the exact receiver and
        raises TypeError when it was never connected.
        """
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
    """_restart() should spawn a new process and quit the current one."""

    def test_restart_spawns_process_and_quits(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_shutdown") as mock_quit:
            app._restart()
            mock_popen.assert_called_once()
            mock_quit.assert_called_once()

    def test_restart_launches_tray_app_on_this_interpreter(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_shutdown"):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert args[0] == sys.executable
            assert args[1] == str(config.PROJECT_DIR / "tray_app.py")

    def test_restart_passes_show_window_when_window_visible(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_shutdown"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow"):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert "--show-window" in args

    def test_restart_omits_show_window_when_window_hidden(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_shutdown"), \
             patch.object(app._window, "isVisible", return_value=False):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert "--show-window" not in args

    def test_restart_grants_foreground_to_child_when_window_visible(self, request):
        app = build_evolver_app(request)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("gui.app.subprocess.Popen", return_value=mock_proc), \
             patch.object(app, "_shutdown"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_called_once_with(12345)

    def test_restart_skips_foreground_grant_when_window_hidden(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen"), \
             patch.object(app, "_shutdown"), \
             patch.object(app._window, "isVisible", return_value=False), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_not_called()


class TestALaunchThatFindsEvolverUp:
    """A second launch is the user clicking Evolver, whose window is hidden in
    the tray — so it must open the running instance's window, not exit. A
    preview's launch is the exception: it came to take the work over."""

    def _launch(self, request, outcome, *, preview=False):
        with override_config(BRANCH_SESSION=preview):
            app = build_evolver_app(request)

        with patch.object(app._instance, "take_over", return_value=outcome) as take_over, \
             patch.object(app._instance, "serve_launches"), \
             patch("gui.app.show_error") as alert, \
             patch("gui.app.crash_log.write_info") as logged:
            exit_code = app.run()

        return exit_code, take_over, alert, logged

    def test_the_usual_evolver_leaves_the_launch_with_the_running_one(self, request):
        exit_code, take_over, _, _ = self._launch(request, Outcome.HANDED_OFF)

        take_over.assert_called_once_with(single_instance.USUAL, end_the_unanswering=False)
        assert exit_code == 0

    def test_a_preview_comes_to_take_the_work_and_ends_an_evolver_that_will_not_answer(
            self, request):
        _, take_over, _, _ = self._launch(request, Outcome.HANDED_OFF, preview=True)

        take_over.assert_called_once_with(single_instance.PREVIEW, end_the_unanswering=True)

    def test_a_taken_handoff_needs_no_dialog(self, request):
        _, _, alert, _ = self._launch(request, Outcome.HANDED_OFF)

        alert.assert_not_called()

    def test_a_handoff_the_running_instance_never_answered_is_visible(self, request):
        """Exiting into silence here is the whole bug: the user clicked Evolver
        and nothing at all happened."""
        exit_code, _, alert, _ = self._launch(request, Outcome.UNANSWERED)

        alert.assert_called_once()
        assert "evolver" in " ".join(alert.call_args[0]).lower()
        assert exit_code == 0

    def test_the_launch_is_logged_as_the_ordinary_event_it_is(self, request):
        """A click on a running app is not a crash, and must not suppress the
        atexit line that says how this process really ended."""
        _, _, _, logged = self._launch(request, Outcome.HANDED_OFF)

        logged.assert_called_once()
        assert "already running" in logged.call_args[0][0].lower()


class TestAnsweringLaunches:
    """The other half: without a listener, every later launch falls through
    to the error dialog and the window still never opens."""

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
        """That launcher predates the answers and exits on the connection, so
        a preview stepping aside for it would leave no Evolver at all."""
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
        """Whoever asked is taking the work over; the broker must not be told
        to leave Evolver down."""
        app, served = self._run_as_first_instance(request)

        with patch.object(app, "_shutdown") as shutdown, \
             patch("gui.app.peer_watch.stand_evolver_down") as stood_down:
            served["on_step_aside"]()

        shutdown.assert_called_once_with()
        stood_down.assert_not_called()

    def test_an_evolver_on_its_way_out_answers_no_more_launches(self, request):
        """A launch answered by an Evolver that is quitting would leave with
        it, and nothing would be running."""
        app = build_evolver_app(request)

        with patch.object(app._instance, "stop_serving") as stop, \
             patch.object(app._app, "quit"):
            app._shutdown()

        stop.assert_called_once_with()


class TestShowWindowFlag:
    """--show-window should open the main window on startup."""

    def test_run_shows_window_when_flag_present(self, request):
        app = build_evolver_app(request)

        with patch.object(app, "_show_window") as mock_show, \
             patch.object(app._instance, "take_over", return_value=Outcome.CLAIMED), \
             patch.object(app._instance, "serve_launches"), \
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
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py"]
            app.run()
            mock_show.assert_not_called()
