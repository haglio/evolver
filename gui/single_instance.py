
from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from enum import Enum

from app_support import processes
from app_support.win32 import try_acquire_mutex
from app_support.win32_loader import load_dll
from PyQt6.QtNetwork import QLocalServer
from shared_ui import running_copy
from shared_ui.running_copy import Answer

from util import crash_log

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
