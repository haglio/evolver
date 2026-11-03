from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG = Path(__file__).resolve().parent.parent / "tray_crash.log"


class _Logged:
    crash = False


class _WarningsIntoTheCrashLog(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        write_info(f"{record.levelname} from {record.name}:", self.format(record) + "\n")


def record_warnings() -> logging.Handler:
    handler = _WarningsIntoTheCrashLog(level=logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def write_crash(header: str, detail: str) -> None:
    _Logged.crash = True
    _append(header, detail)


def write_info(header: str, detail: str) -> None:
    _append(header, detail)


def on_exit() -> None:
    if not _Logged.crash:
        _append("Clean exit", "".join(traceback.format_stack()))


def install_excepthook() -> None:
    # Without this, an exception in a Qt slot is a silent abort() under pythonw, which has no stderr.
    def _hook(exc_type, exc_value, exc_tb):
        write_crash(
            "Unhandled exception in Qt callback:",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.exit(1)

    sys.excepthook = _hook


def _append(header: str, detail: str) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with CRASH_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {header}\n{detail}")
