"""Tests for gui.startup -- the Start-with-Windows shortcut.

The Startup folder is redirected through APPDATA into a temp tree.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support import windows_settings
from app_support.win32 import read_shortcut

from gui import startup
from tests.temp_helpers import override_config, workspace_temp_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SHORTCUT = "Evolver in the tray.lnk"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="a shortcut: only Windows can say")


@pytest.fixture
def startup_dir():
    with workspace_temp_dir() as tmp, patch.dict("os.environ", {"APPDATA": str(tmp)}):
        folder = tmp / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        folder.mkdir(parents=True)
        yield folder


@on_windows
class TestRegisterStartup:

    def test_the_shortcut_is_the_one_evolvers_list_keeps_in_the_startup_folder(self, startup_dir):
        """So "Start with Windows" and the command that keeps the machine in step
        with every app's list never write two different shortcuts."""
        with override_config(LIVE_DIR=REPO_ROOT):
            startup.register_startup()

        (spec,) = [spec for spec in windows_settings.declared(REPO_ROOT).shortcuts
                   if "startup" in spec.places]
        written = read_shortcut(str(startup_dir / SHORTCUT))
        assert windows_settings.what_differs(
            written, windows_settings.shortcut_for(REPO_ROOT, spec)) == []

    def test_it_starts_evolver_only_if_it_is_not_running(self, startup_dir):
        with override_config(LIVE_DIR=REPO_ROOT):
            startup.register_startup()

        written = read_shortcut(str(startup_dir / SHORTCUT))
        assert written.arguments == f'"{REPO_ROOT / "launch_evolver_if_not_running.vbs"}"'
        assert Path(written.working_directory) == REPO_ROOT

    def test_a_branch_preview_still_points_it_at_the_evolver_that_runs_every_day(self, startup_dir):
        """A preview is the whole app, settings dialog included, and ticking
        "Start with Windows" there must not leave Windows starting a branch."""
        with workspace_temp_dir() as live, override_config(LIVE_DIR=live):
            shutil.copy(REPO_ROOT / "pyproject.toml", live / "pyproject.toml")
            startup.register_startup()

            written = read_shortcut(str(startup_dir / SHORTCUT))
            assert written.arguments == f'"{live / "launch_evolver_if_not_running.vbs"}"'
            assert Path(written.working_directory) == live


class TestUnregisterStartup:

    def test_removes_the_shortcut(self, startup_dir):
        (startup_dir / SHORTCUT).write_bytes(b"shortcut")
        assert startup.is_registered()

        startup.unregister_startup()

        assert not startup.is_registered()
        assert not (startup_dir / SHORTCUT).exists()

    def test_is_a_noop_when_no_shortcut_exists(self, startup_dir):
        assert not startup.is_registered()
        startup.unregister_startup()  # must not raise
        assert not startup.is_registered()
