#!/usr/bin/env pythonw
"""Evolver system tray application entry point.

Launch with: pythonw.exe tray_app.py
"""

import atexit
import sys
import traceback

from util import crash_log
from util.windows_alert import show_error_window


def _name_this_process() -> None:
    """Leave the shortcut an interpreter that says "Evolver" next time.

    Windows takes what it shows about a process from the file it was started
    from -- the Details tab's name, the Processes tab's description, the icon
    beside it -- so a plain ``pythonw.exe`` puts Evolver in the task list as one
    more anonymous "Python".  That costs nothing until something strands a
    process, and then the task list is the only way back and cannot say which
    row is safe to end.

    Naming this process on the way in is the one thing that cannot be done:
    writing the copy takes the very interpreter being named.  So each run makes
    it for the run after, and its pinned shortcut points at it once it exists.
    """
    try:
        from pathlib import Path as _Path

        from app_support.process_identity import ProcessNamer

        icon = _Path(__file__).resolve().parent / "icon.ico"
        ProcessNamer("Evolver", icon=icon).prepare_launcher("Evolver")
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def main():
    crash_log.install_excepthook()
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
    show_error_window(
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
