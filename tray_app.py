#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import atexit
import sys
import traceback
from pathlib import Path

from app_support.process_identity import ProcessNamer

from util import crash_log
from util.alert import show_error

_ICON = Path(__file__).resolve().parent / "icon.ico"


def _name_this_process() -> None:
    """Leave the pinned shortcut an interpreter that says "Evolver" next time.
    Why it is one launch behind, and why it can never cost the launch:
    :meth:`ProcessNamer.name_this_process`.  A failure is logged, and main()
    routes warnings into the crash log, so the task list filling with anonymous
    Pythons is never a thing nothing anywhere records."""
    ProcessNamer("Evolver", icon=_ICON).name_this_process("Evolver")


def main():
    crash_log.install_excepthook()
    crash_log.record_warnings()
    _name_this_process()
    atexit.register(crash_log.on_exit)
    from gui.app import EvolverApp
    sys.exit(EvolverApp().run())


def report_startup_crash(detail: str) -> None:
    """Record a failed startup, and put it somewhere the user will actually see.

    Nothing is on screen yet and pythonw.exe has no stderr, so a log entry alone
    leaves them looking at a launcher that did nothing at all — which is how a
    missing dependency once went unnoticed for a day.
    """
    crash_log.write_crash("Startup crash:", detail)
    show_error(
        "Evolver failed to start",
        f"{detail.strip().splitlines()[-1]}\n\nFull details: {crash_log.CRASH_LOG}",
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        report_startup_crash(traceback.format_exc())
        sys.exit(1)
