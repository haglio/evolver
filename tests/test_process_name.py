"""Evolver says its own name in the Windows task list.

Why an app names its processes, and why its own is the one it can only name for
the run after, is :mod:`app_support.process_identity`'s to say.  What is left
here is what only this repo can be wrong about: that the app makes the copy its
shortcut starts it through, run against a throwaway venv rather than read off
``tray_app.py``, and that a failure to make it leaves a trace where this app
keeps its traces.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support.process_identity_check import assert_the_app_names_its_process

import tray_app
from util import crash_log

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "Evolver"
ROLE = "Evolver"


def test_the_app_prepares_the_copy_for_next_time(tmp_path: Path):
    """From the windowed interpreter, which is what the shortcut starts;
    described as the app's name alone -- one app with one window, so the row is
    its name, not its name twice; carrying the app's own mark; and never taking
    a launch down when there is nothing to copy from."""
    assert_the_app_names_its_process(
        tray_app._name_this_process, tmp_path, app_name=APP_NAME, role=ROLE,
        interpreter="pythonw.exe", row=APP_NAME, icon=PROJECT_DIR / "icon.ico")


def test_a_failure_to_name_leaves_a_trace(monkeypatch: pytest.MonkeyPatch):
    """Silently, the task list is full of anonymous Pythons and nothing anywhere
    says why -- which is the state this whole mechanism exists to end.  The
    naming logs its failure, and main() routes warnings into the crash log,
    because under pythonw a warning nobody routed goes nowhere."""
    monkeypatch.setattr(sys, "executable", "")  # nothing to copy from
    handler = crash_log.record_warnings()
    try:
        with patch("util.crash_log.write_info") as write_info:
            tray_app._name_this_process()
    finally:
        logging.getLogger().removeHandler(handler)

    write_info.assert_called_once()
    assert "naming" in " ".join(str(arg) for arg in write_info.call_args[0]).lower()
