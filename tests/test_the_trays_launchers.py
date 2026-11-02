from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAY_LAUNCHER = REPO_ROOT / "launch_evolver.vbs"
SHORTCUT_LAUNCHER = REPO_ROOT / "launch_evolver_from_its_shortcut.vbs"
IF_NOT_RUNNING_LAUNCHER = REPO_ROOT / "launch_evolver_if_not_running.vbs"
SHOWING_LAUNCHER = REPO_ROOT / "launch_evolver_showing_its_window.vbs"
PREVIEW_LAUNCHER = REPO_ROOT / "launch_preview_branch.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launcher_the_brokers_tray_spells_is_there():
    assert IF_NOT_RUNNING_LAUNCHER.is_file()


@on_windows
def test_the_pinned_shortcut_starts_the_same_tray_with_the_loading_screen_up_from_the_click():
    tray, clicked = dry_run(TRAY_LAUNCHER), dry_run(SHORTCUT_LAUNCHER)

    assert clicked.value("interpreter") == tray.value("interpreter")
    assert clicked.value("arguments") == tray.value("arguments")
    assert "app_support.loading_screen" in clicked.value("loading screen")
    assert tray.values("loading screen") == []


@on_windows
def test_the_start_for_when_evolver_is_not_running_is_the_same_tray_saying_so():
    tray, if_not_running = dry_run(TRAY_LAUNCHER), dry_run(IF_NOT_RUNNING_LAUNCHER)

    assert if_not_running.value("interpreter") == tray.value("interpreter")
    assert if_not_running.value("directory") == tray.value("directory")
    assert if_not_running.value("arguments") == f'{tray.value("arguments")} --if-not-running'


@on_windows
def test_a_restart_from_the_window_is_the_same_tray_showing_it():
    tray, showing = dry_run(TRAY_LAUNCHER), dry_run(SHOWING_LAUNCHER)

    assert showing.value("interpreter") == tray.value("interpreter")
    assert showing.value("arguments") == f'{tray.value("arguments")} --show-window'


@on_windows
def test_a_preview_is_the_same_tray_as_a_branch_session_with_the_primarys_overlay():
    report = dry_run(PREVIEW_LAUNCHER)

    primary = REPO_ROOT.parents[2]
    assert report.value("arguments") == f'"{REPO_ROOT / "tray_app.py"}" --show-window'
    assert report.values("environment") == ["EVOLVER_BRANCH_SESSION=1"]
    assert report.value("copy") == (
        f"{primary / 'content.local.json'} > {REPO_ROOT / 'content.local.json'}")
