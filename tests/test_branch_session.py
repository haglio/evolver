"""A branch session: the whole app out of a worktree, in place of the usual Evolver.

What it shares with the usual one (the library, the run history and its log,
the queue's lists, the settings), the work it takes over from it (the
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
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
from PyQt6.QtWidgets import QMessageBox
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from gui import branch_session
from tests.gui_support import build_evolver_app
from tests.temp_helpers import override_config

REPO_ROOT = Path(__file__).resolve().parents[1]

_PATHS = ("PROJECT_DIR", "LIVE_DIR", "LOG_FILE", "RUNS_DIR", "GUI_SETTINGS_FILE",
          "NONAI_SKIP_LIST", "NONAI_PIN_LIST")


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
             patch("gui.main_window.newest_runs", return_value=[]), \
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
        assert app._window.pause_action.isEnabled()

    def test_starting_it_is_asking_for_evolver_so_an_earlier_stand_down_goes(self, request):
        app = self._preview(request)

        cleared = self._started(app)

        cleared.assert_called_once_with()

    def test_the_usual_evolver_hands_nothing_back(self, request):
        app = build_evolver_app(request)

        self._started(app)

        assert not app._session._hand_back.isActive()


def _session(*, preview: bool, a_run_is_going: bool = False):
    """A session over a stand-in gateway, with the steps of leaving recorded in order."""
    steps = Mock()
    with override_config(BRANCH_SESSION=preview):
        session = branch_session.BranchSession(steps.gateway, lambda: a_run_is_going)
    session.leaving.connect(steps.leaving)
    return session, steps


class TestHandingTheWorkBack:
    """A preview forgotten about must not run a branch's pipeline over the
    library for good: the usual Evolver takes back over."""

    def _started_preview(self, request):
        with override_config(BRANCH_SESSION=True):
            app = build_evolver_app(request)
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.newest_runs", return_value=[]), \
             patch("gui.app.peer_watch.clear_evolver_stand_down"):
            app.start()
        return app

    def test_once_it_has_had_its_time_it_makes_way_for_the_usual_evolver(self):
        """The claim goes first, so the usual Evolver can take it at once: one
        from before launches spoke hands its launch to whoever holds the
        claim, which would open the preview's window instead."""
        session, steps = _session(preview=True)
        session.take_the_work()

        assert session._hand_back.isActive()
        assert session._hand_back.interval() == branch_session.HAND_BACK_AFTER_MINUTES * 60_000
        with patch("gui.branch_session.start_the_usual_evolver", steps.start_the_usual_evolver):
            session._hand_back.timeout.emit()

        assert steps.mock_calls == [call.gateway.let_go(), call.start_the_usual_evolver(),
                                    call.leaving()]

    def test_a_run_in_flight_is_let_finish_first(self):
        """Quitting gives the stage in flight five seconds, and the run it
        belongs to is the branch's own work."""
        session, steps = _session(preview=True, a_run_is_going=True)
        session.take_the_work()

        with patch("gui.branch_session.start_the_usual_evolver", steps.start_the_usual_evolver):
            session._hand_back.timeout.emit()

        assert steps.mock_calls == []
        assert session._hand_back.isActive()
        assert session._hand_back.interval() == branch_session.HAND_BACK_RETRY_MS

    def test_the_usual_evolver_never_starts_the_hour(self):
        session, _steps = _session(preview=False)

        session.take_the_work()

        assert not session._hand_back.isActive()

    def test_quitting_a_preview_hands_the_work_back_at_once(self):
        session, steps = _session(preview=True)

        with patch("gui.branch_session.start_the_usual_evolver", steps.start_the_usual_evolver), \
             patch("gui.peer_watch.stand_evolver_down") as stood_down:
            session.quit()

        assert steps.mock_calls == [call.gateway.let_go(), call.start_the_usual_evolver(),
                                    call.leaving()]
        stood_down.assert_not_called()

    def test_quitting_the_usual_evolver_stands_it_down_and_leaves(self):
        """The one quit the broker honors: every other way Evolver goes down is
        undone within the quarter hour."""
        session, steps = _session(preview=False)

        with patch("gui.branch_session.start_the_usual_evolver", steps.start_the_usual_evolver), \
             patch("gui.peer_watch.stand_evolver_down", steps.stand_evolver_down):
            session.quit()

        assert steps.mock_calls == [call.stand_evolver_down(), call.leaving()]

    def test_stepping_aside_leaves_without_standing_evolver_down(self):
        """Whoever asked is taking the work over; the broker must not be told
        to leave Evolver down."""
        session, steps = _session(preview=False)

        with patch("gui.peer_watch.stand_evolver_down", steps.stand_evolver_down), \
             patch("util.crash_log.write_info") as logged:
            session.step_aside()

        assert steps.mock_calls == [call.leaving()]
        assert "stepping aside" in logged.call_args.args[0].lower()

    def test_the_windows_quit_says_the_work_goes_back_before_it_does(self, request):
        app = self._started_preview(request)

        with patch("gui.app.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No) as asked, \
             patch("gui.branch_session.start_the_usual_evolver") as started:
            app._confirm_quit()

        assert "Your usual Evolver takes the work back" in asked.call_args.args[2]
        started.assert_not_called()

    def test_leaving_the_work_quits_the_app(self, request):
        app = build_evolver_app(request)

        with patch.object(app._app, "quit") as quit_the_application:
            app._session.leaving.emit()

        quit_the_application.assert_called_once_with()

    def test_the_window_says_when_the_work_goes_back(self, request):
        with patch("util.preview.preview_of", return_value=Preview(feature="the new queue window")):
            app = self._started_preview(request)

        assert app._window.windowTitle().startswith("Evolver — preview of the new queue window")
        assert ", until " in app._window.windowTitle()

    def test_the_usual_evolver_is_started_from_its_own_checkout_and_not_as_a_preview(self):
        """It inherits this process's environment, and the flag in it would
        make the Evolver started to take back over one more preview."""
        with override_config(LIVE_DIR=Path("C:/live/evolver")), \
             patch.dict(os.environ, {"EVOLVER_BRANCH_SESSION": "1"}), \
             patch("gui.branch_session.subprocess.Popen") as popen:
            branch_session.start_the_usual_evolver()

        popen.assert_called_once()
        assert Path(popen.call_args.args[0][1]).parent == Path("C:/live/evolver")
        assert popen.call_args.kwargs["cwd"] == str(Path("C:/live/evolver"))
        assert "EVOLVER_BRANCH_SESSION" not in popen.call_args.kwargs["env"]
        assert popen.call_args.kwargs["env"]["PATH"] == os.environ["PATH"]

    def test_the_usual_evolver_is_started_only_if_none_is_running(self):
        with override_config(LIVE_DIR=Path("C:/live/evolver")), \
             patch("gui.branch_session.subprocess.Popen") as popen:
            branch_session.start_the_usual_evolver()

        assert popen.call_args.args[0] == [
            "wscript.exe", str(Path("C:/live/evolver") / "launch_evolver_if_not_running.vbs")]

    def test_the_usual_evolver_loads_its_own_modules_rather_than_the_preview_s(self):
        a_sibling_branch_the_preview_was_tried_with = "C:/workspace/shared_ui/.claude/worktrees/a-change"
        with override_config(LIVE_DIR=Path("C:/live/evolver")), \
             patch.dict(os.environ, {"EVOLVER_BRANCH_SESSION": "1",
                                     "PYTHONPATH": a_sibling_branch_the_preview_was_tried_with}), \
             patch("gui.branch_session.subprocess.Popen") as popen:
            branch_session.start_the_usual_evolver()

        assert "PYTHONPATH" not in popen.call_args.kwargs["env"]


class TestTellingTheTwoApart:
    def test_the_window_and_the_tray_name_the_feature_the_preview_demos(self, request):
        with override_config(BRANCH_SESSION=True), \
             patch("util.preview.preview_of", return_value=Preview(feature="the new queue window")):
            app = build_evolver_app(request)

        assert "preview of the new queue window" in app._window.windowTitle()
        assert "preview of the new queue window" in app._tray.toolTip()

    def test_a_preview_s_tray_icon_wears_its_letter_in_the_preview_ink(self, request):
        with override_config(BRANCH_SESSION=True), \
             patch("util.preview.preview_of", return_value=Preview(feature=None)):
            app = build_evolver_app(request)

        middle_of_the_e = app._tray.icon().pixmap(256, 256).toImage().pixelColor(128, 128)
        assert (middle_of_the_e.red(), middle_of_the_e.green(), middle_of_the_e.blue()) == PREVIEW_INK

    def test_a_preview_gets_a_taskbar_button_of_its_own(self):
        with override_config(BRANCH_SESSION=True), \
             patch("util.preview.preview_of", return_value=Preview(feature=None)):
            assert branch_session.model_id("Evolver.TrayApp") == "Evolver.TrayApp.Preview"

    def test_the_live_app_is_just_evolver(self, request):
        app = build_evolver_app(request)

        assert app._window.windowTitle() == "Evolver"
        assert app._tray.toolTip().startswith("Evolver")
