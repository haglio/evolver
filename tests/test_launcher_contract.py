"""What Evolver's launchers run, asked of each under the real script host.

The broker's tray spells launch_evolver_if_not_running.vbs in its own config, so
the names are pinned here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import assert_launchers_match_their_specs, dry_run

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAY_LAUNCHER = REPO_ROOT / "launch_evolver.vbs"
IF_NOT_RUNNING_LAUNCHER = REPO_ROOT / "launch_evolver_if_not_running.vbs"
PREVIEW_LAUNCHER = REPO_ROOT / "launch_preview_branch.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launchers_are_where_their_callers_point():
    assert TRAY_LAUNCHER.is_file()
    assert IF_NOT_RUNNING_LAUNCHER.is_file()
    assert PREVIEW_LAUNCHER.is_file()


def test_the_launchers_are_what_their_specs_render():
    assert_launchers_match_their_specs(REPO_ROOT)


@on_windows
def test_the_tray_runs_windowed_from_this_checkout_on_its_venv():
    """pythonw, not python: the tray is a GUI app and must not flash a console."""
    report = dry_run(TRAY_LAUNCHER)

    assert Path(report.value("interpreter")).parent == REPO_ROOT / ".venv" / "Scripts"
    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == f'"{REPO_ROOT / "tray_app.py"}"'
    assert report.values("log") == []


@on_windows
def test_the_start_for_when_evolver_is_not_running_is_the_same_tray_saying_so():
    tray, if_not_running = dry_run(TRAY_LAUNCHER), dry_run(IF_NOT_RUNNING_LAUNCHER)

    assert if_not_running.value("interpreter") == tray.value("interpreter")
    assert if_not_running.value("directory") == tray.value("directory")
    assert if_not_running.value("arguments") == f'{tray.value("arguments")} --if-not-running'
    assert if_not_running.values("log") == []


@on_windows
def test_a_preview_runs_this_worktree_as_a_branch_session_with_the_primarys_overlay():
    """The whole app, in place of the usual Evolver: the same tray_app the daily
    launcher runs, marked a branch session so the running one steps aside.  The
    overlay is where library_root and project_roots live, so a copy taken weeks
    ago resolves a library that has moved; it is brought across every time."""
    report = dry_run(PREVIEW_LAUNCHER)

    primary = REPO_ROOT.parents[2]
    assert Path(report.value("interpreter")) == primary / ".venv" / "Scripts" / "pythonw.exe"
    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == f'"{REPO_ROOT / "tray_app.py"}" --show-window'
    assert report.values("environment") == ["EVOLVER_BRANCH_SESSION=1"]
    assert Path(report.value("log")) == REPO_ROOT / "state" / "preview_branch.log"
    assert report.value("copy") == (
        f"{primary / 'content.local.json'} > {REPO_ROOT / 'content.local.json'}")
