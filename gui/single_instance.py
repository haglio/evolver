"""Who owns the single Evolver instance, and what a launch does about one already up.

Two mechanisms, answering two different questions — keep both:

* the **mutex** answers *may I run?*  Never two Evolvers, because two schedulers
  mean two pipelines and stacked Topaz encodes, which is what used to exhaust
  memory and crash the computer.
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
from enum import Enum

from app_support.win32 import try_acquire_mutex
from app_support.win32_loader import load_dll
from PyQt6.QtNetwork import QLocalServer
from shared_ui import running_copy
from shared_ui.running_copy import Answer

from util import crash_log, processes

log = logging.getLogger(__name__)

_kernel32 = load_dll("kernel32")

_MUTEX_NAME = "EvolverTrayApp_SingleInstance"
_PIPE_NAME = "EvolverTrayApp_ShowWindow"

_PATIENCE_SECONDS = 30.0
_RETRY_SECONDS = 0.2

USUAL = b"usual"
PREVIEW = b"preview"

SHOWING = b"showing"
STEPPING_ASIDE = b"stepping-aside"

IF_NOT_RUNNING = "--if-not-running"


class Outcome(Enum):
    CLAIMED = "claimed"
    HANDED_OFF = "handed_off"
    UNANSWERED = "unanswered"
    LEFT_AS_IT_WAS = "left_as_it_was"


class InstanceGateway:
    def __init__(self):
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

    def become_evolver(self, *, as_preview: bool, only_if_not_running: bool) -> Outcome:
        if only_if_not_running:
            if self.claim():
                return Outcome.CLAIMED
            crash_log.write_info(
                "Already running:", f"a start with {IF_NOT_RUNNING} left it as it was\n")
            return Outcome.LEFT_AS_IT_WAS
        outcome = self.take_over(PREVIEW if as_preview else USUAL, end_the_unanswering=as_preview)
        if outcome is not Outcome.CLAIMED:
            crash_log.write_info(
                "Already running:", "duplicate launch handed to the running instance\n")
        return outcome

    def take_over(self, launch: bytes, *, end_the_unanswering: bool) -> Outcome:
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
        def _answer(launch: bytes, reply: Callable[[bytes], None]) -> None:
            if steps_aside_for(launch):
                self.stop_serving()
                reply(STEPPING_ASIDE)
                on_step_aside()
            else:
                reply(SHOWING)
                on_show()

        server = running_copy.listen(_PIPE_NAME, _answer)
        if not server.isListening():
            log.error("Cannot listen on %s: %s", _PIPE_NAME, server.errorString())
        self._launches = server

    def stop_serving(self) -> None:
        if self._launches is not None:
            self._launches.close()

    def let_go(self) -> None:
        self.stop_serving()
        if self._mutex_handle is not None:
            _kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
            self._mutex_handle = None

    def ask(self, launch: bytes, *, until: float) -> Answer | None:
        return running_copy.ask(_PIPE_NAME, launch, until=until)


def _end(pid: int) -> bool:
    log.warning("Evolver (process %s) did not answer; ending it", pid)
    return processes.terminate(pid)
