"""A branch session: the whole app out of a worktree, in place of the usual Evolver.

What it shares with the usual one (the library, the run history and its log,
the queue's manifests, the settings), the work it takes over from it (the
schedule, the supervision), and how that work goes back are the whole
contract, and all three are held here.

The config half runs in a fresh interpreter, because the flag is read at import
and the suite's own import happened long before any test could set it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
from PyQt6.QtWidgets import QMessageBox

from gui import branch_session
from tests.gui_support import build_evolver_app
from tests.temp_helpers import override_config

REPO_ROOT = Path(__file__).resolve().parents[1]

_PATHS = ("PROJECT_DIR", "LIVE_DIR", "LOG_FILE", "RUNS_DIR", "GUI_SETTINGS_FILE",
          "NONAI_SKIP_MANIFEST", "NONAI_PRIORITY_MANIFEST")


def config_paths(branch_session: bool) -> dict[str, Path]:
    """What ``config`` resolves those paths to, with and without the flag.

    A fresh interpreter under the repo root, as the launcher starts one, and on
    the committed example overlay, which is what a public checkout has.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "EVOLVER_BRANCH_SESSION")}
    if branch_session:
        env["EVOLVER_BRANCH_SESSION"] = "1"
    driver = (
        "import json;"
        "import content_overlay as c;"
        "c.LOCAL_CONTENT = c.EXAMPLE_CONTENT;"
        "import config;"
        f"print(json.dumps({{name: str(getattr(config, name)) for name in {_PATHS!r}}}))"
    )
    done = subprocess.run([sys.executable, "-c", driver], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return {name: Path(value) for name, value in json.loads(done.stdout).items()}


class TestWhatABranchSessionShares:
    """The files a preview must not keep to itself, or it shows a history
    nobody made and a queue nobody ordered."""

    @pytest.fixture(scope="class")
    def preview(self):
        return config_paths(branch_session=True)

    @pytest.fixture(scope="class")
    def ordinary(self):
        return config_paths(branch_session=False)

    def test_a_preview_reads_and_writes_the_live_checkouts_files(self, preview):
        live = preview["LIVE_DIR"]

        assert live != preview["PROJECT_DIR"]
        assert live.name == "evolver"
        assert [name for name in _PATHS[2:] if preview[name].parent != live] == []

    def test_an_ordinary_run_keeps_them_in_the_checkout_it_runs_from(self, ordinary):
        assert ordinary["LIVE_DIR"] == ordinary["PROJECT_DIR"]
        assert [name for name in _PATHS[2:] if ordinary[name].parent != ordinary["PROJECT_DIR"]] == []


class TestWhatABranchSessionTakesOver:
    """A preview is the whole app, and the app is its schedule: one Evolver
    at a time runs the ten-minute pipeline, parks the encode for the user's
    presence, and keeps the broker up -- and while a preview runs, that is
    the preview."""

    def _preview(self, request):
        with override_config(BRANCH_SESSION=True):
            return build_evolver_app(request)

    def _started(self, app):
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.load_runs", return_value=[]), \
             patch("gui.app.peer_watch.clear_evolver_stand_down") as cleared:
            app.start()
        return cleared

    def test_it_keeps_the_schedule_and_the_watches_it_took_over(self, request):
        app = self._preview(request)

        self._started(app)

        assert app._presence.is_running
        assert app._peer_timer.isActive()
        assert app._scheduler.next_run_at is not None
        assert app._tray.pause_action.isEnabled()
        assert app._window.active_toggle.isEnabled()

    def test_starting_it_is_asking_for_evolver_so_an_earlier_stand_down_goes(self, request):
        app = self._preview(request)

        cleared = self._started(app)

        cleared.assert_called_once_with()

    def test_the_usual_evolver_hands_nothing_back(self, request):
        app = build_evolver_app(request)

        self._started(app)

        assert not app._hand_back.isActive()


class TestHandingTheWorkBack:
    """A preview forgotten about must not run a branch's pipeline over the
    library for good: the usual Evolver takes back over."""

    def _started_preview(self, request):
        with override_config(BRANCH_SESSION=True):
            app = build_evolver_app(request)
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.load_runs", return_value=[]), \
             patch("gui.app.peer_watch.clear_evolver_stand_down"):
            app.start()
        return app

    def _handing_back(self, app):
        """The three steps of handing back, recorded in the order they ran."""
        steps = Mock()
        return steps, ExitStack(), [
            patch.object(app._instance, "let_go", steps.let_go),
            patch("gui.branch_session.start_the_usual_evolver", steps.start_the_usual_evolver),
            patch.object(app, "_shutdown", steps.shutdown),
        ]

    def test_once_it_has_had_its_time_it_makes_way_for_the_usual_evolver(self, request):
        """The claim goes first, so the usual Evolver can take it at once: one
        from before launches spoke hands its launch to whoever holds the
        claim, which would open the preview's window instead."""
        app = self._started_preview(request)
        steps, stack, patches = self._handing_back(app)

        assert app._hand_back.isActive()
        assert app._hand_back.interval() == branch_session.HAND_BACK_AFTER_MINUTES * 60_000
        with stack:
            for each in patches:
                stack.enter_context(each)
            app._hand_back.timeout.emit()

        assert steps.mock_calls == [call.let_go(), call.start_the_usual_evolver(),
                                    call.shutdown()]

    def test_a_run_in_flight_is_let_finish_first(self, request):
        """Quitting gives the stage in flight five seconds, and the run it
        belongs to is the branch's own work."""
        app = self._started_preview(request)
        steps, stack, patches = self._handing_back(app)

        with stack, patch.object(type(app._runs), "is_running", new=True):
            for each in patches:
                stack.enter_context(each)
            app._hand_back.timeout.emit()

        assert steps.mock_calls == []
        assert app._hand_back.isActive()

    def test_quitting_a_preview_hands_the_work_back_at_once(self, request):
        app = self._started_preview(request)
        steps, stack, patches = self._handing_back(app)

        with stack, patch("gui.app.peer_watch.stand_evolver_down") as stood_down:
            for each in patches:
                stack.enter_context(each)
            app._quit_by_request()

        assert steps.mock_calls == [call.let_go(), call.start_the_usual_evolver(),
                                    call.shutdown()]
        stood_down.assert_not_called()

    def test_the_windows_quit_says_the_work_goes_back_before_it_does(self, request):
        app = self._started_preview(request)

        with patch("gui.app.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No) as asked, \
             patch("gui.branch_session.start_the_usual_evolver") as started:
            app._confirm_quit()

        assert "Your usual Evolver takes the work back" in asked.call_args.args[2]
        started.assert_not_called()

    def test_quitting_the_usual_evolver_still_stands_it_down(self, request):
        app = build_evolver_app(request)

        with patch("gui.branch_session.start_the_usual_evolver") as started, \
             patch("gui.app.peer_watch.stand_evolver_down") as stood_down, \
             patch.object(app, "_shutdown"):
            app._quit_by_request()

        started.assert_not_called()
        stood_down.assert_called_once_with()

    def test_the_window_says_when_the_work_goes_back(self, request):
        with patch("gui.branch_session.branch", return_value="claude/some-change"):
            app = self._started_preview(request)

        assert app._window.windowTitle().startswith("Evolver — preview of claude/some-change")
        assert ", until " in app._window.windowTitle()

    def test_the_usual_evolver_is_started_from_its_own_checkout_and_not_as_a_preview(self):
        """It inherits this process's environment, and the flag in it would
        make the Evolver started to take back over one more preview."""
        with override_config(LIVE_DIR=Path("C:/live/evolver")), \
             patch.dict(os.environ, {"EVOLVER_BRANCH_SESSION": "1"}), \
             patch("gui.branch_session.subprocess.Popen") as popen:
            branch_session.start_the_usual_evolver()

        popen.assert_called_once()
        assert popen.call_args.args[0] == [
            "wscript.exe", str(Path("C:/live/evolver") / "launch_evolver.vbs")]
        assert popen.call_args.kwargs["cwd"] == str(Path("C:/live/evolver"))
        assert "EVOLVER_BRANCH_SESSION" not in popen.call_args.kwargs["env"]
        assert popen.call_args.kwargs["env"]["PATH"] == os.environ["PATH"]


class TestTellingTheTwoApart:
    def test_the_window_and_the_tray_name_the_branch(self, request):
        with override_config(BRANCH_SESSION=True), \
             patch("gui.branch_session.branch", return_value="claude/some-change"):
            app = build_evolver_app(request)

        assert "claude/some-change" in app._window.windowTitle()
        assert "claude/some-change" in app._tray.toolTip()

    def test_the_live_app_is_just_evolver(self, request):
        app = build_evolver_app(request)

        assert app._window.windowTitle() == "Evolver"
        assert app._tray.toolTip().startswith("Evolver")
