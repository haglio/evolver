"""A branch session: the whole app out of a worktree, beside the live Evolver.

What it shares with the live app (the library, the run history and its log, the
queue's manifests, the settings) and what it leaves to it (the schedule, the
supervision) are the whole contract, and both halves are held here.

The config half runs in a fresh interpreter, because the flag is read at import
and the suite's own import happened long before any test could set it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


class TestWhatABranchSessionLeavesToTheLiveApp:
    """A preview does what it is clicked to do and nothing on a timer: two
    schedules would run two pipelines, and two presence polls would suspend the
    one encode twice over and thaw it once."""

    def _preview(self, request):
        with override_config(BRANCH_SESSION=True):
            return build_evolver_app(request)

    def _started(self, app):
        with patch("gui.app.process_identity.claim"), \
             patch("gui.main_window.load_runs", return_value=[]), \
             patch("gui.app.peer_watch.clear_evolver_stand_down") as cleared:
            app.start()
        return cleared

    def test_it_starts_no_schedule_and_no_watch_of_its_own(self, request):
        app = self._preview(request)

        self._started(app)

        assert not app._presence.is_running
        assert not app._peer_timer.isActive()
        assert app._scheduler.next_run_at is None

    def test_starting_it_leaves_the_live_evolvers_stand_down_alone(self, request):
        """That marker says the user quit the Evolver they run; a preview
        coming up is not them asking for that one back."""
        app = self._preview(request)

        cleared = self._started(app)

        cleared.assert_not_called()

    def test_quitting_it_does_not_stand_the_live_evolver_down(self, request):
        app = self._preview(request)

        with patch("gui.app.peer_watch.stand_evolver_down") as stood_down, \
             patch.object(app, "_shutdown"):
            app._quit_by_request()

        stood_down.assert_not_called()

    def test_the_schedule_is_not_this_instances_to_pause(self, request):
        app = self._preview(request)

        assert not app._tray.pause_action.isEnabled()
        assert not app._window.active_toggle.isEnabled()
        assert "keeps the schedule" in app._window.active_toggle.toolTip()

    def test_the_live_app_still_starts_everything(self, request):
        app = build_evolver_app(request)

        cleared = self._started(app)

        assert app._presence.is_running
        assert app._peer_timer.isActive()
        assert app._scheduler.next_run_at is not None
        assert app._tray.pause_action.isEnabled()
        cleared.assert_called_once_with()


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

    def test_a_preview_claims_its_own_instance_so_neither_refuses_the_other(self, request):
        with override_config(BRANCH_SESSION=True):
            preview = build_evolver_app(request)
        live = build_evolver_app(request)

        assert preview._instance.names() != live._instance.names()
