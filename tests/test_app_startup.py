"""Smoke test: verify the tray app can be constructed without crashing."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gui.app import _wire
from gui.process_identity import APP_MODEL_ID
from tests.gui_support import build_evolver_app


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
        with patch("gui.process_identity.ctypes.windll.shell32"
                   ".SetCurrentProcessExplicitAppUserModelID") as mock_set_id, \
             patch("gui.process_identity.set_taskbar_properties"):
            app.start()
        mock_set_id.assert_called_once_with(APP_MODEL_ID)


class TestBuildingIsNotStarting:
    """Constructing an EvolverApp touches nothing outside the process.

    It used to name this process to the shell, set taskbar properties on a
    window handle, read the whole run-history directory off disk and begin a
    twenty-second presence poll -- so a test that wanted any one part paid for
    all of them, and left a live timer behind for the rest of the session.
    """

    def test_construction_claims_no_identity(self, request):
        with patch("gui.app.process_identity.claim") as claim:
            build_evolver_app(request)
        claim.assert_not_called()

    def test_construction_starts_neither_timer(self, request):
        app = build_evolver_app(request)
        assert not app._presence_monitor.isActive()
        assert not app._watchdog.isActive()

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
        assert app._presence_monitor.isActive()
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
        app._progress_popup = popup

        app._on_finished(self._finished_record())

        popup.on_pipeline_finished.assert_called_once_with()
        assert app._progress_popup is None

    def test_an_errored_run_lets_go_of_it_too(self, request):
        app = build_evolver_app(request)
        popup = MagicMock()
        app._progress_popup = popup

        app._on_error("something went wrong")

        popup.on_pipeline_finished.assert_called_once_with()
        assert app._progress_popup is None

    def test_a_finished_run_stops_the_watchdog_and_re_opens_scheduling(self, request):
        app = build_evolver_app(request)
        with patch("gui.app.PipelineWorker"):
            app._start_run("manual")
        assert app._watchdog.isActive()

        app._on_finished(self._finished_record())

        assert not app._watchdog.isActive()
        assert not app._scheduler.is_running

    def test_an_errored_run_does_the_same(self, request):
        app = build_evolver_app(request)
        with patch("gui.app.PipelineWorker"):
            app._start_run("manual")

        app._on_error("something went wrong")

        assert not app._watchdog.isActive()
        assert not app._scheduler.is_running


class TestToastPolicy:
    """One place decides whether a tray balloon is shown at all."""

    def _app(self, request, *, enable_toasts):
        from gui.settings import EvolverSettings
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
        with patch("gui.app.PipelineWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            app._start_run("manual")

        with patch.object(app._tray, "showMessage") as toast:
            app._on_watchdog()
            app._on_error("boom")
            app._on_finished(self._record())

        toast.assert_not_called()

    def test_toasts_on_says_something_for_each_of_the_three(self, request):
        app = self._app(request, enable_toasts=True)
        with patch("gui.app.PipelineWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            app._start_run("manual")

        with patch.object(app._tray, "showMessage") as toast:
            app._on_watchdog()
            app._on_error("boom")
            app._on_finished(self._record())

        assert toast.call_count == 3


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


class TestNonAiUpscaleToggle:
    """The tray menu's opt-in switch for the multi-hour non-AI encodes."""

    def _app_with_fresh_settings(self, request):
        from gui.settings import EvolverSettings
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
        with patch("gui.app.PipelineWorker") as mock_worker:
            app._start_run("manual")
        assert mock_worker.call_args.kwargs["nonai_enabled"]


class TestPresenceMonitor:
    """A fast timer keeps the in-flight encode in step with the user between
    the slow pipeline ticks."""

    def _app_with_toggle(self, request, enabled):
        from gui.settings import EvolverSettings
        settings = EvolverSettings()
        settings.nonai_upscale_enabled = enabled
        with patch("gui.app.EvolverSettings.load", return_value=settings):
            return build_evolver_app(request)

    def test_monitor_timer_runs_once_the_app_is_started(self, request):
        app = self._app_with_toggle(request, True)
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.load_runs", return_value=[]):
            app.start()
        assert app._presence_monitor.isActive()

    def test_throttles_the_encode_while_the_toggle_is_on(self, request):
        app = self._app_with_toggle(request, True)
        with patch("gui.app.nonai_upscale.throttle_to_presence") as mock_throttle:
            app._throttle_presence()
        mock_throttle.assert_called_once_with()

    def test_leaves_the_encode_alone_while_the_toggle_is_off(self, request):
        app = self._app_with_toggle(request, False)
        with patch("gui.app.nonai_upscale.throttle_to_presence") as mock_throttle:
            app._throttle_presence()
        mock_throttle.assert_not_called()


class TestSessionManagement:
    """EvolverApp must log Windows session-management events that could kill it."""

    def test_connects_to_commit_data_request(self, request):
        """The session-end handler is wired to the signal, not merely defined.

        This used to assert ``hasattr(app, "_on_session_end")``, which stays
        true with the connect line deleted — and then Windows shutdown
        force-kills the tray with a running pipeline behind it. The signal
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
        with patch.object(app, "_quit") as mock_quit, \
             patch("gui.app.crash_log.write_info"):
            app._on_session_end(mock_manager)

        mock_quit.assert_called_once()


class TestRestart:
    """_restart() should spawn a new process and quit the current one."""

    def test_restart_spawns_process_and_quits(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit") as mock_quit:
            app._restart()
            mock_popen.assert_called_once()
            mock_quit.assert_called_once()

    def test_restart_launches_tray_app_on_this_interpreter(self, request):
        import sys as real_sys

        import config

        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert args[0] == real_sys.executable
            assert args[1] == str(config.PROJECT_DIR / "tray_app.py")

    def test_restart_passes_show_window_when_window_visible(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow"):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert "--show-window" in args

    def test_restart_omits_show_window_when_window_hidden(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=False):
            app._restart()
            args = mock_popen.call_args[0][0]
            assert "--show-window" not in args

    def test_restart_grants_foreground_to_child_when_window_visible(self, request):
        app = build_evolver_app(request)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("gui.app.subprocess.Popen", return_value=mock_proc), \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_called_once_with(12345)

    def test_restart_skips_foreground_grant_when_window_hidden(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.subprocess.Popen"), \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=False), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_not_called()


class TestDuplicateLaunchHandoff:
    """A second launch is the user clicking Evolver, whose window is hidden in
    the tray — so it must open the running instance's window, not exit."""

    def _duplicate_launch(self, request, handoff_taken):
        app = build_evolver_app(request)

        with patch("gui.app.single_instance.is_first_instance", return_value=False), \
             patch("gui.app.single_instance.request_show", return_value=handoff_taken) as show_request, \
             patch("gui.app.show_error_window") as alert, \
             patch("gui.app.crash_log.write_info") as logged:
            exit_code = app.run()

        return exit_code, show_request, alert, logged

    def test_duplicate_asks_the_running_instance_to_show_its_window(self, request):
        exit_code, show_request, _, _ = self._duplicate_launch(request, handoff_taken=True)

        show_request.assert_called_once_with()
        assert exit_code == 0

    def test_a_taken_handoff_needs_no_dialog(self, request):
        _, _, alert, _ = self._duplicate_launch(request, handoff_taken=True)

        alert.assert_not_called()

    def test_a_handoff_the_running_instance_never_answered_is_visible(self, request):
        """Exiting into silence here is the whole bug: the user clicked Evolver
        and nothing at all happened."""
        _, _, alert, _ = self._duplicate_launch(request, handoff_taken=False)

        alert.assert_called_once()
        assert "evolver" in " ".join(alert.call_args[0]).lower()

    def test_the_launch_is_logged_as_the_ordinary_event_it_is(self, request):
        """A click on a running app is not a crash, and must not suppress the
        atexit line that says how this process really ended."""
        _, _, _, logged = self._duplicate_launch(request, handoff_taken=True)

        logged.assert_called_once()
        assert "already running" in logged.call_args[0][0].lower()


class TestServingDuplicateLaunches:
    """The other half of the handoff: without a listener, every duplicate launch
    falls through to the error dialog and the window still never opens."""

    def _run_as_first_instance(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.single_instance.is_first_instance", return_value=True), \
             patch("gui.app.single_instance.serve_show_requests") as serve, \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py"]
            app.run()

        return app, serve

    def test_first_instance_listens_for_them(self, request):
        _, serve = self._run_as_first_instance(request)

        serve.assert_called_once()

    def test_what_it_registered_opens_the_window(self, request):
        app, serve = self._run_as_first_instance(request)

        with patch.object(app._window, "show") as mock_show, \
             patch.object(app._window, "raise_"), \
             patch.object(app._window, "activateWindow"):
            serve.call_args[0][0]()

        mock_show.assert_called_once()

    def test_the_listener_is_held_past_the_call_that_made_it(self, request):
        """A QLocalServer nothing refers to is collected, and the pipe closes
        with it — the handoff would then fail for reasons no log would show."""
        app, serve = self._run_as_first_instance(request)

        assert app._show_requests is serve.return_value


class TestShowWindowFlag:
    """--show-window should open the main window on startup."""

    def test_run_shows_window_when_flag_present(self, request):
        app = build_evolver_app(request)

        with patch.object(app, "_show_window") as mock_show, \
             patch("gui.app.single_instance.is_first_instance", return_value=True), \
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
             patch("gui.app.single_instance.is_first_instance", return_value=True), \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py"]
            app.run()
            mock_show.assert_not_called()
