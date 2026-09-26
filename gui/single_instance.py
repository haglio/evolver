"""Who owns the single Evolver instance, and what a launch does about one already up.

Two mechanisms, answering two different questions — keep both:

* the **mutex** answers *may I run?*  Never two Evolvers, because two schedulers
  mean two pipelines and stacked Topaz encodes, which is what used to exhaust
  memory and crash the machine.
* the **pipe** answers *what should the one already running do about me?*  A
  tray app's window is hidden, so clicking Evolver — a shortcut, the Start
  menu, or the taskbar pin, whose relaunch command Windows re-runs verbatim —
  starts a second process whose real job is to open the first one's window.
  And a branch's preview (``gui/branch_session.py``) is launched to take the
  work over, so the one running has to get out of its way.

A launch says which of the two it is; the running Evolver answers whether it
is opening its window or stepping aside.  An Evolver from before launches said
anything answers nothing, and opens its window on the connection alone.

A wedged instance still holds the mutex while answering nothing on the pipe, so
the caller learns both answers and can say so rather than exiting into silence.

Both are one object because both are held for the process's life: Windows lets
a named mutex go when the last handle to it closes, and a collected server
closes the pipe with it. Held as two loose module globals, the second was a
return value the caller had to remember to keep -- which is a rule no reader of
the caller can see, and one nothing would have failed on.
"""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app_support.win32 import try_acquire_mutex
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from util import processes
from util.win32_loader import load_dll

log = logging.getLogger(__name__)

_kernel32 = load_dll("kernel32")

# Neither name can change: an Evolver started before a change is not refused by
# one started after it, and its window cannot be handed a launch.
_MUTEX_NAME = "EvolverTrayApp_SingleInstance"
_PIPE_NAME = "EvolverTrayApp_ShowWindow"

# How long a launch waits for the Evolver already running to answer, and again
# for it to go: stepping aside, it gives the stage it is in five seconds to
# finish, and a machine under load can keep it from the processor for seconds
# on end -- starved of it, one took fifteen to answer.
_PATIENCE_SECONDS = 30.0
_RETRY_SECONDS = 0.2
_SEND_TIMEOUT_MS = 2000

#: What a launch says when it finds an Evolver already running: the Evolver
#: the user runs every day, or a branch's, come to take the work over.
USUAL = b"usual"
PREVIEW = b"preview"

#: What the running Evolver answers.
SHOWING = b"showing"
STEPPING_ASIDE = b"stepping-aside"


class Outcome(Enum):
    """What a launch came to."""

    #: This process is Evolver now.
    CLAIMED = "claimed"
    #: The Evolver already running took the launch, and opened its window.
    HANDED_OFF = "handed_off"
    #: An Evolver holds the claim and could not be reached to answer.
    UNANSWERED = "unanswered"


@dataclass(frozen=True)
class Answer:
    """What the running Evolver said to a launch, and which process said it."""

    reply: bytes
    pid: int


class InstanceGateway:
    """This process's claim on being *the* Evolver, and the pipe under it."""

    def __init__(self):
        # Each handle IS the thing it claims, so both live as long as this does.
        self._mutex_handle: int | None = None
        self._launches: QLocalServer | None = None

    def claim(self) -> bool:
        """Claim the named mutex. True when no other Evolver holds it.

        False also when Windows would not make the mutex at all.  "Could not
        check" is not "checked": a second scheduler is the failure this guards
        against, so a refusal to create the mutex is a refusal to run, not a
        licence to.
        """
        self._mutex_handle = try_acquire_mutex(_MUTEX_NAME)
        return self._mutex_handle is not None

    def take_over(self, launch: bytes, *, end_the_unanswering: bool) -> Outcome:
        """Become Evolver, or leave this launch with the one already running.

        An Evolver stepping aside is waited out, for as long as its last run's
        stage takes to finish. One that answers nothing is ended when
        *end_the_unanswering*, which is how a preview takes the work from an
        Evolver older than the answers; any other launch leaves it be, since
        such an Evolver opens its window on the connection alone.
        """
        deadline = time.monotonic() + _PATIENCE_SECONDS
        while not self.claim():
            if time.monotonic() >= deadline:
                return Outcome.UNANSWERED
            answer = self.ask(launch, until=deadline)
            if answer is not None:
                if answer.reply == SHOWING:
                    return Outcome.HANDED_OFF
                if answer.reply != STEPPING_ASIDE and not end_the_unanswering:
                    return Outcome.HANDED_OFF
                if answer.reply == STEPPING_ASIDE or _end(answer.pid):
                    deadline = time.monotonic() + _PATIENCE_SECONDS
            time.sleep(_RETRY_SECONDS)
        return Outcome.CLAIMED

    def serve_launches(self, *, steps_aside_for: Callable[[bytes], bool],
                       on_show: Callable[[], None],
                       on_step_aside: Callable[[], None]) -> None:
        """Answer every launch that finds this Evolver running.

        *steps_aside_for* is handed what the launch said -- ``b""`` from a
        launcher that says nothing -- and decides. Stepping aside stops the
        listening first, so no later launch is answered by an Evolver on its
        way out.
        """
        server = QLocalServer()
        QLocalServer.removeServer(_PIPE_NAME)  # only ours to take: we hold the mutex
        if not server.listen(_PIPE_NAME):
            # Not fatal — this instance still works. But nothing can hand a
            # launch to it, so say why here rather than in a dialog the user
            # cannot act on.
            log.error("Cannot listen on %s: %s", _PIPE_NAME, server.errorString())

        def _answer(connection: QLocalSocket, launch: bytes) -> None:
            if steps_aside_for(launch):
                self.stop_serving()
                _reply(connection, launch, STEPPING_ASIDE)
                on_step_aside()
            else:
                _reply(connection, launch, SHOWING)
                on_show()

        def _accept():
            connection = server.nextPendingConnection()
            if connection is not None:
                _hear(connection, _answer)

        server.newConnection.connect(_accept)
        self._launches = server

    def stop_serving(self) -> None:
        """Stop answering launches: this Evolver is on its way out."""
        if self._launches is not None:
            self._launches.close()

    def let_go(self) -> None:
        """Stop answering launches and give up the claim, before this process exits.

        How a preview hands the work back: the Evolver it starts next can
        claim at once, however long this one takes to wind down.
        """
        self.stop_serving()
        if self._mutex_handle is not None:
            _kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
            self._mutex_handle = None

    def ask(self, launch: bytes, *, until: float) -> Answer | None:
        """Tell the running Evolver what *launch* is, and hear by *until* what it does.

        None when nothing is listening -- an Evolver still starting, or one on
        its way out.
        """
        socket = QLocalSocket()
        socket.connectToServer(_PIPE_NAME)
        if not socket.waitForConnected(_milliseconds_until(until)):
            return None
        pid = processes.pipe_server(int(socket.socketDescriptor()))
        socket.write(launch)
        socket.waitForBytesWritten(_milliseconds_until(until))
        reply = b""
        if socket.waitForReadyRead(_milliseconds_until(until)):
            reply = bytes(socket.readAll())
        socket.disconnectFromServer()
        return Answer(reply, pid)


def _end(pid: int) -> bool:
    log.warning("Evolver (process %s) did not answer; ending it", pid)
    return processes.terminate(pid)


def _milliseconds_until(moment: float) -> int:
    return max(0, round((moment - time.monotonic()) * 1000))


def _reply(connection: QLocalSocket, launch: bytes, reply: bytes) -> None:
    if launch:
        connection.write(reply)
        connection.waitForBytesWritten(_SEND_TIMEOUT_MS)
    connection.disconnectFromServer()
    connection.deleteLater()


def _hear(connection: QLocalSocket, answer: Callable[[QLocalSocket, bytes], None]) -> None:
    """Hand *answer* what the launch on *connection* said, once it has said it.

    A launch says its piece and waits; one from before launches spoke hangs up
    having said nothing, and that hang-up is its whole message.
    """
    answered = []

    def _once(launch: bytes) -> None:
        if not answered:
            answered.append(True)
            answer(connection, launch)

    connection.readyRead.connect(lambda: _once(bytes(connection.readAll())))
    connection.disconnected.connect(lambda: _once(b""))
    if connection.bytesAvailable():
        _once(bytes(connection.readAll()))
