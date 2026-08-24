"""Windows dialog helpers."""

import ctypes
import logging

log = logging.getLogger(__name__)


def show_error_window(title: str, message: str) -> None:
    _show_window(title, message, 0x10, "error")


def _message_box_w(hwnd: int, text: str, caption: str, flags: int) -> int:
    """``user32.MessageBoxW``, reached by a name of ours.

    A suite has to gag this before it runs anything: one unguarded call blocks
    on a human for as long as the run lasts.  Gagging it through
    ``ctypes.windll`` means resolving that dotted path at import, and off
    Windows there is no such path -- so the gag, not the platform, is what
    decides whether the suite collects.  A name here is resolvable everywhere.
    """
    return ctypes.windll.user32.MessageBoxW(hwnd, text, caption, flags)


def _show_window(title: str, message: str, icon_flag: int, level: str) -> None:
    try:
        result = _message_box_w(0, message, title, icon_flag)
        log.info("MessageBoxW returned %d", result)
    except Exception:
        log.exception("Failed to show Windows %s dialog: %s", level, title)
