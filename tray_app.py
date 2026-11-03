#!/usr/bin/env pythonw
from __future__ import annotations

import atexit
import sys
import traceback
from pathlib import Path

from app_support.process_identity import ProcessNamer

from util import crash_log
from util.alert import show_error

_ICON = Path(__file__).resolve().parent / "icon.ico"


def _name_this_process() -> None:
    ProcessNamer("Evolver", icon=_ICON).name_this_process("Evolver")


def main():
    crash_log.install_excepthook()
    crash_log.record_warnings()
    _name_this_process()
    atexit.register(crash_log.on_exit)
    # Late: a Qt or dependency failure must raise inside the try below.
    from shared_ui.application import application  # noqa: PLC0415

    from gui.app import EvolverApp  # noqa: PLC0415
    with application(sys.argv) as app:
        sys.exit(EvolverApp(app).run())


def report_startup_crash(detail: str) -> None:
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
