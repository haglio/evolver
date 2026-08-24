"""Who owns the single Evolver instance, and what a second launch does instead.

Two mechanisms, answering two different questions — keep both:

* the **mutex** answers *may I run?*  Never two Evolvers, because two schedulers
  mean two pipelines and stacked Topaz encodes, which is what used to exhaust
  memory and crash the machine.
* the **pipe** answers *can I hand this launch to the instance already running?*
  A tray app's window is hidden, so clicking Evolver — a shortcut, the Start
  menu, or the taskbar pin, whose relaunch command Windows re-runs verbatim —
  starts a second process whose real job is to open the first one's window.

A wedged instance still holds the mutex while answering nothing on the pipe, so
the caller learns both answers and can say so rather than exiting into silence.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from util.win32_loader import load_dll

log = logging.getLogger(__name__)

_MUTEX_NAME = "EvolverTrayApp_SingleInstance"
_PIPE_NAME = "EvolverTrayApp_ShowWindow"

_CONNECT_TIMEOUT_MS = 3000

_kernel32 = load_dll("kernel32", use_last_error=True)
_CreateMutexW = _kernel32.CreateMutexW
_CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_CreateMutexW.restype = ctypes.c_void_p


def is_first_instance() -> bool:
    """Claim the named mutex. True when no other Evolver holds it.

    Uses use_last_error=True + ctypes.get_last_error() so the error code is
    captured atomically at the C level, immune to clobbering by injected DLLs
    (e.g. Windhawk) that may call Win32 functions inside CreateMutexW hooks.
    """
    _ERROR_ALREADY_EXISTS = 183
    handle = _CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True  # CreateMutex failed entirely; proceed anyway
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def serve_show_requests(on_show: Callable[[], None]) -> QLocalServer:
    """Listen for duplicate launches and run *on_show* for each one.

    The caller must hold the returned server: dropping it closes the pipe, and
    every later launch then falls through to the "not responding" dialog.
    """
    server = QLocalServer()
    QLocalServer.removeServer(_PIPE_NAME)  # only ours to take: we hold the mutex
    if not server.listen(_PIPE_NAME):
        # Not fatal — this instance still works. But nothing can hand a launch
        # to it, so say why here rather than in a dialog the user cannot act on.
        log.error("Cannot listen on %s: %s", _PIPE_NAME, server.errorString())

    def _accept():
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
            connection.deleteLater()
        on_show()

    server.newConnection.connect(_accept)
    return server


def request_show(timeout_ms: int = _CONNECT_TIMEOUT_MS) -> bool:
    """Ask the running instance to open its window. True if it took the request.

    The connection itself is the whole message — there is no payload to get
    wrong, and a refused connection is exactly the case the caller must handle.
    """
    socket = QLocalSocket()
    socket.connectToServer(_PIPE_NAME)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.disconnectFromServer()
    return True
