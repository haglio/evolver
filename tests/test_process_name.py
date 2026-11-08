from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support.process_identity_check import ProcessName, assert_the_process_is_named

import tray_app
from util import crash_log

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "Evolver"
ROLE = "Evolver"


def test_the_copy_is_of_the_windowed_interpreter_the_shortcut_starts_and_its_row_is_the_one_apps_name(
        tmp_path: Path):
    assert_the_process_is_named(
        tray_app._name_this_process, tmp_path,
        ProcessName(
            app_name=APP_NAME,
            role=ROLE,
            interpreter="pythonw.exe",
            row=APP_NAME,
            icon=PROJECT_DIR / "icon.ico",
        ),
    )


def test_a_failure_to_name_leaves_a_trace(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "executable", "")
    handler = crash_log.record_warnings()
    try:
        with patch("util.crash_log.write_info") as write_info:
            tray_app._name_this_process()
    finally:
        logging.getLogger().removeHandler(handler)

    write_info.assert_called_once()
    assert "naming" in " ".join(str(arg) for arg in write_info.call_args[0]).lower()
