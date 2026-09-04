"""Evolver's half of the pair: what it checks, what it starts, and when it doesn't.

The policy itself — the throttle, the stand-down, the guard around a failing
launcher — is app_support's and is tested there. What is tested here is the part
only Evolver can get wrong: which mutex answers "is the broker up", which file is
run to start one, and that no quit except the user's own leaves a mark.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import config
from gui import peer_watch
from tests.gui_support import build_evolver_app


class TestIsTheBrokerUp:
    def test_a_held_tray_mutex_is_a_running_broker(self):
        assert peer_watch.broker_tray_is_up(is_held=lambda name: True) is True

    def test_a_free_tray_mutex_is_a_broker_that_is_gone(self):
        assert peer_watch.broker_tray_is_up(is_held=lambda name: False) is False

    def test_it_asks_after_the_tray_rather_than_the_broker_process(self):
        """The tray is the broker's own supervisor, and the thing to restart.

        Asking after the broker process instead would fight the tray's own Pause,
        which stops the broker and leaves the tray running on purpose.
        """
        asked: list[str] = []

        peer_watch.broker_tray_is_up(is_held=lambda name: asked.append(name) or True)

        assert asked == ["Global\\OSR2Broker.Tray"]


class TestStartingTheBroker:
    def test_it_runs_the_launcher_through_the_script_host(self, tmp_path):
        launcher = tmp_path / "launch_broker_tray.vbs"
        launcher.write_text("' launcher", encoding="utf-8")
        popen = MagicMock()

        with patch("gui.peer_watch.crash_log.write_info"):
            peer_watch.launch_broker_tray(launcher=launcher, popen=popen)

        argv = popen.call_args[0][0]
        assert argv == ["wscript.exe", str(launcher)]

    def test_it_runs_the_launcher_from_the_brokers_own_directory(self, tmp_path):
        launcher = tmp_path / "launch_broker_tray.vbs"
        launcher.write_text("' launcher", encoding="utf-8")
        popen = MagicMock()

        with patch("gui.peer_watch.crash_log.write_info"):
            peer_watch.launch_broker_tray(launcher=launcher, popen=popen)

        assert popen.call_args.kwargs["cwd"] == str(tmp_path)

    def test_it_never_flashes_a_console_over_whatever_is_on_screen(self, tmp_path):
        launcher = tmp_path / "launch_broker_tray.vbs"
        launcher.write_text("' launcher", encoding="utf-8")
        popen = MagicMock()

        with patch("gui.peer_watch.crash_log.write_info"):
            peer_watch.launch_broker_tray(launcher=launcher, popen=popen)

        import subprocess
        assert popen.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW

    def test_a_checkout_with_no_broker_beside_it_starts_nothing(self, tmp_path):
        popen = MagicMock()

        peer_watch.launch_broker_tray(launcher=tmp_path / "absent.vbs", popen=popen)

        popen.assert_not_called()

    def test_a_launch_is_written_where_the_tray_log_always_works(self, tmp_path):
        """Not the module logger: Evolver's root logger gets its handler from the
        first pipeline run, so a start-up launch would go nowhere."""
        launcher = tmp_path / "launch_broker_tray.vbs"
        launcher.write_text("' launcher", encoding="utf-8")

        with patch("gui.peer_watch.crash_log.write_info") as write_info:
            peer_watch.launch_broker_tray(launcher=launcher, popen=MagicMock())

        write_info.assert_called_once()
        assert "broker" in write_info.call_args[0][0].lower()

    def test_the_default_launcher_is_the_brokers_own(self):
        assert config.BROKER_TRAY_LAUNCHER.name == "launch_broker_tray.vbs"
        assert config.BROKER_TRAY_LAUNCHER.parent.name == "broker"


class TestTheWatch:
    def test_a_broker_that_is_up_is_left_alone(self):
        with patch("gui.peer_watch.broker_tray_is_up", return_value=True), \
             patch("gui.peer_watch.launch_broker_tray") as launch:
            peer_watch.watch_the_broker().tick()

        launch.assert_not_called()

    def test_a_broker_that_is_gone_is_started(self):
        with patch("gui.peer_watch.broker_tray_is_up", return_value=False), \
             patch("gui.peer_watch.launch_broker_tray") as launch, \
             patch("app_support.peer_watch.is_stood_down", return_value=False):
            peer_watch.watch_the_broker().tick()

        launch.assert_called_once()

    def test_a_broker_the_user_closed_is_left_closed(self):
        with patch("gui.peer_watch.broker_tray_is_up", return_value=False), \
             patch("gui.peer_watch.launch_broker_tray") as launch, \
             patch("app_support.peer_watch.is_stood_down", return_value=True):
            peer_watch.watch_the_broker().tick()

        launch.assert_not_called()

    def test_the_watch_asks_after_the_key_the_broker_stands_itself_down_under(self):
        asked: list[str] = []

        with patch("gui.peer_watch.broker_tray_is_up", return_value=False), \
             patch("gui.peer_watch.launch_broker_tray"), \
             patch("app_support.peer_watch.is_stood_down",
                   side_effect=lambda key, **kw: asked.append(key) or False):
            peer_watch.watch_the_broker().tick()

        assert asked == ["broker"]


class TestTheAppKeepsTheWatch:
    """Wiring: the timer, the first check, and which quits leave a mark."""

    def test_the_app_checks_on_the_broker_as_it_starts(self, request):
        app = build_evolver_app(request)

        with patch.object(app._peer, "tick") as tick, \
             patch("gui.app.process_identity.claim"):
            app.start()

        tick.assert_called_once()

    def test_the_app_keeps_checking_on_a_timer(self, request):
        app = build_evolver_app(request)

        with patch.object(app._peer, "tick"), patch("gui.app.process_identity.claim"):
            app.start()

        assert app._peer_timer.isActive()
        assert app._peer_timer.interval() == peer_watch.PEER_CHECK_INTERVAL_MS

    def test_starting_takes_evolver_off_any_earlier_stand_down(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.peer_watch.clear_evolver_stand_down") as clear, \
             patch.object(app._peer, "tick"), patch("gui.app.process_identity.claim"):
            app.start()

        clear.assert_called_once()

    def test_quitting_from_the_tray_stands_evolver_down(self, request):
        app = build_evolver_app(request)

        with patch("gui.app.peer_watch.stand_evolver_down") as stand_down, \
             patch.object(app, "_shutdown"):
            app._quit_by_request()

        stand_down.assert_called_once()

    def test_windows_ending_the_session_does_not(self, request):
        """The event Windows sends before a shutdown it may then cancel.

        Evolver quits itself on it, and every long outage in its log starts
        there. Marking that as deliberate would be marking the exact deaths this
        pairing exists to undo.
        """
        app = build_evolver_app(request)

        with patch("gui.app.peer_watch.stand_evolver_down") as stand_down, \
             patch.object(app, "_shutdown"), patch("gui.app.crash_log.write_info"):
            app._on_session_end(MagicMock())

        stand_down.assert_not_called()

    def test_restarting_does_not(self, request):
        """A restart is Evolver on its way back up, not on its way down."""
        app = build_evolver_app(request)

        with patch("gui.app.peer_watch.stand_evolver_down") as stand_down, \
             patch("gui.app.subprocess.Popen"), patch.object(app, "_shutdown"):
            app._restart()

        stand_down.assert_not_called()

    def test_shutting_down_stops_the_timer(self, request):
        app = build_evolver_app(request)

        with patch.object(app._peer, "tick"), patch("gui.app.process_identity.claim"):
            app.start()
        with patch.object(app._app, "quit"):
            app._shutdown()

        assert not app._peer_timer.isActive()
