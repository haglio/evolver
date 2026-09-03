"""The Windows error dialog Evolver shows when a stage cannot continue."""

import ctypes
import logging

log = logging.getLogger(__name__)


_MB_ICONERROR = 0x10


def show_error_window(title: str, message: str) -> None:
    try:
        result = _message_box_w(0, message, title, _MB_ICONERROR)
        log.info("MessageBoxW returned %d", result)
    except Exception:
        log.exception("Failed to show Windows error dialog: %s", title)


def _message_box_w(hwnd: int, text: str, caption: str, flags: int) -> int:
    """``user32.MessageBoxW``, reached by a name of ours.

    A suite has to gag this before it runs anything: one unguarded call blocks
    on a human for as long as the run lasts.  Gagging it through
    ``ctypes.windll`` means resolving that dotted path at import, and off
    Windows there is no such path -- so the gag, not the platform, is what
    decides whether the suite collects.  A name here is resolvable everywhere.
    """
    return ctypes.windll.user32.MessageBoxW(hwnd, text, caption, flags)
