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

Both are one object because both are held for the process's life: Windows lets
a named mutex go when the last handle to it closes, and a collected server
closes the pipe with it. Held as two loose module globals, the second was a
return value the caller had to remember to keep -- which is a rule no reader of
the caller can see, and one nothing would have failed on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app_support.win32 import try_acquire_mutex
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

# Neither name can change: an Evolver started before a change is not refused by
# one started after it, and its window cannot be handed a launch.
_MUTEX_NAME = "EvolverTrayApp_SingleInstance"
_PIPE_NAME = "EvolverTrayApp_ShowWindow"

_CONNECT_TIMEOUT_MS = 3000


class InstanceGateway:
    """This process's claim on being *the* Evolver, and the pipe under it."""

    def __init__(self):
        # Each handle IS the thing it claims, so both live as long as this does.
        self._mutex_handle: int | None = None
        self._show_requests: QLocalServer | None = None

    def claim(self) -> bool:
        """Claim the named mutex. True when no other Evolver holds it.

        False also when Windows would not make the mutex at all.  "Could not
        check" is not "checked": a second scheduler is the failure this guards
        against, so a refusal to create the mutex is a refusal to run, not a
        licence to.
        """
        self._mutex_handle = try_acquire_mutex(_MUTEX_NAME)
        return self._mutex_handle is not None

    def serve_show_requests(self, on_show: Callable[[], None]) -> None:
        """Listen for duplicate launches and run *on_show* for each one."""
        server = QLocalServer()
        QLocalServer.removeServer(_PIPE_NAME)  # only ours to take: we hold the mutex
        if not server.listen(_PIPE_NAME):
            # Not fatal — this instance still works. But nothing can hand a
            # launch to it, so say why here rather than in a dialog the user
            # cannot act on.
            log.error("Cannot listen on %s: %s", _PIPE_NAME, server.errorString())

        def _accept():
            connection = server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
                connection.deleteLater()
            on_show()

        server.newConnection.connect(_accept)
        self._show_requests = server

    def hand_off(self) -> bool:
        """Ask the running instance to open its window. True if it took it.

        The connection itself is the whole message — there is no payload to get
        wrong, and a refused connection is exactly the case the caller must
        handle.
        """
        socket = QLocalSocket()
        socket.connectToServer(_PIPE_NAME)
        if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        socket.disconnectFromServer()
        return True
