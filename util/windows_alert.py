"""Windows dialog helpers."""

import ctypes
import logging

log = logging.getLogger(__name__)


def show_error_window(title: str, message: str) -> None:
    _show_window(title, message, 0x10, "error")


def show_info_window(title: str, message: str) -> None:
    _show_window(title, message, 0x40, "info")


def _show_window(title: str, message: str, icon_flag: int, level: str) -> None:
    try:
        result = ctypes.windll.user32.MessageBoxW(0, message, title, icon_flag)
        log.info("MessageBoxW returned %d", result)
    except Exception:
        log.exception("Failed to show Windows %s dialog: %s", level, title)
