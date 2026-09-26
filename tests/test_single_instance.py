"""Tests for single-instance ownership, and what a launch does about an Evolver already up."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from gui import single_instance
from tests.gui_support import QAPP


class TestIsFirstInstance(unittest.TestCase):
    """The mutex must be immune to GetLastError clobbering by injected DLLs
    (e.g. Windhawk)."""

    def test_the_first_evolver_to_ask_is_given_the_claim(self):
        unique = f"TestMutex_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique):
            self.assertTrue(single_instance.InstanceGateway().claim())

    def test_letting_go_frees_the_claim_while_this_process_lives_on(self):
        """How a preview hands the work back: the Evolver it starts must be
        able to claim however long this one takes to exit."""
        with patch.object(single_instance, "_MUTEX_NAME", _unique("LetGoMutex")),              patch.object(single_instance, "_PIPE_NAME", _unique("LetGoPipe")):
            holder = single_instance.InstanceGateway()
            self.assertTrue(holder.claim())
            self.assertFalse(single_instance.InstanceGateway().claim())

            holder.let_go()

            self.assertTrue(single_instance.InstanceGateway().claim())

    def test_a_second_evolver_is_refused_while_the_first_holds_the_claim(self):
        unique = f"TestMutex_Dup_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique), held_mutex(unique):
            self.assertFalse(single_instance.InstanceGateway().claim())


class held_mutex:
    """The named mutex held the way another Evolver holds it, until let go."""

    def __init__(self, name: str):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._name = name
        self._handle = None

    def __enter__(self):
        self._handle = self._kernel32.CreateMutexW(None, False, self._name)
        assert self._handle, "Setup: CreateMutexW should succeed"
        return self

    def let_go(self):
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __exit__(self, *exc):
        self.let_go()


def _pump_until(condition, deadline_seconds: float = 10.0) -> bool:
    """Spin the shared event loop until *condition* holds, or the deadline passes."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        QAPP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _unique(label: str) -> str:
    return f"EvolverTest_{label}_{os.getpid()}_{time.monotonic_ns()}"


def _ask(launch: bytes) -> single_instance.Answer | None:
    return single_instance.InstanceGateway().ask(launch, until=time.monotonic() + 10.0)


def in_the_background(work):
    """Run *work* on a thread while this one serves, and hand back its result.

    The launch blocks on the running Evolver's answer, and the running Evolver
    answers from the event loop -- which, in one test process, is this thread.
    """
    done = []
    thread = threading.Thread(target=lambda: done.append(work()), daemon=True)
    thread.start()
    _pump_until(lambda: not thread.is_alive(), deadline_seconds=40.0)
    assert done, "the launch never finished"
    return done[0]


class _Calls(list):
    """A record of calls that also does *then* on each, as a process exiting would."""

    def __init__(self, then):
        super().__init__()
        self._then = then

    def append(self, item):
        super().append(item)
        self._then()


class Listening:
    """A running Evolver's side of the pipe, recording what it was asked to do."""

    def __init__(self, *, steps_aside_for=lambda launch: False):
        self.shown = []
        self.stepped_aside = []
        self.gateway = single_instance.InstanceGateway()
        self.gateway.serve_launches(
            steps_aside_for=steps_aside_for,
            on_show=lambda: self.shown.append(True),
            on_step_aside=lambda: self.stepped_aside.append(True))

    def close(self):
        self.gateway.stop_serving()


class Unanswering:
    """An Evolver that takes the connection and says nothing, ever."""

    def __init__(self):
        self._held = []
        self._server = QLocalServer()
        QLocalServer.removeServer(single_instance._PIPE_NAME)
        assert self._server.listen(single_instance._PIPE_NAME), self._server.errorString()
        self._server.newConnection.connect(
            lambda: self._held.append(self._server.nextPendingConnection()))

    def close(self):
        self._server.close()


class AnswersBeforeHearing:
    """A running Evolver's pipe that answers a launch the moment it connects, takes in
    what the launch said only a moment later, and hangs up."""

    def __init__(self, reply: bytes, heard: bytes):
        self._kernel32 = kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, number = ctypes.c_void_p, ctypes.c_uint32
        kernel32.CreateNamedPipeW.argtypes = [ctypes.c_wchar_p, *[number] * 6, handle]
        kernel32.CreateNamedPipeW.restype = handle
        kernel32.ConnectNamedPipe.argtypes = [handle, handle]
        kernel32.FlushFileBuffers.argtypes = [handle]
        kernel32.DisconnectNamedPipe.argtypes = [handle]
        kernel32.CloseHandle.argtypes = [handle]
        kernel32.WriteFile.argtypes = [handle, ctypes.c_char_p, number, ctypes.POINTER(number),
                                       handle]
        kernel32.ReadFile.argtypes = kernel32.WriteFile.argtypes
        duplex, one_instance, unbuffered = 3, 1, 0
        self._pipe = self._kernel32.CreateNamedPipeW(
            "\\\\.\\pipe\\" + single_instance._PIPE_NAME, duplex, 0, one_instance,
            unbuffered, unbuffered, 0, None)
        assert self._pipe not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
        self._reply = reply
        self._heard = ctypes.create_string_buffer(len(heard))
        self._serving = threading.Thread(target=self._serve, daemon=True)
        self._serving.start()

    def _serve(self):
        moved = ctypes.c_uint32()
        self._kernel32.ConnectNamedPipe(self._pipe, None)
        self._kernel32.WriteFile(self._pipe, self._reply, len(self._reply), ctypes.byref(moved),
                                 None)
        time.sleep(0.1)
        self._kernel32.ReadFile(self._pipe, self._heard, len(self._heard), ctypes.byref(moved),
                                None)
        self._kernel32.FlushFileBuffers(self._pipe)
        self._kernel32.DisconnectNamedPipe(self._pipe)

    def close(self):
        self._serving.join(timeout=10)
        self._kernel32.CloseHandle(self._pipe)


class TestAskingTheRunningOne(unittest.TestCase):
    """A launch that finds Evolver up says what it is, and hears what the
    running one does about it."""

    def test_nothing_listening_is_no_answer(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Absent")):
            self.assertIsNone(_ask(single_instance.USUAL))

    def test_the_running_one_says_it_steps_aside_and_which_process_it_is(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Aside")):
            running = Listening(steps_aside_for=lambda launch: launch == single_instance.PREVIEW)
            try:
                answer = in_the_background(
                    lambda: _ask(single_instance.PREVIEW))
                _pump_until(lambda: running.stepped_aside)
            finally:
                running.close()

        self.assertEqual(answer, single_instance.Answer(single_instance.STEPPING_ASIDE,
                                                        os.getpid()))
        self.assertEqual((running.stepped_aside, running.shown), ([True], []))

    def test_a_launch_it_does_not_step_aside_for_opens_its_window(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Show")):
            running = Listening()
            try:
                answer = in_the_background(
                    lambda: _ask(single_instance.USUAL))
                _pump_until(lambda: running.shown)
            finally:
                running.close()

        self.assertEqual(answer.reply, single_instance.SHOWING)
        self.assertEqual((running.shown, running.stepped_aside), ([True], []))

    def test_an_answer_in_before_the_launch_has_finished_speaking_is_heard(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Early")):
            running = AnswersBeforeHearing(single_instance.STEPPING_ASIDE,
                                           heard=single_instance.PREVIEW)
            try:
                answer = _ask(single_instance.PREVIEW)
            finally:
                running.close()

        self.assertEqual(answer.reply, single_instance.STEPPING_ASIDE)

    def test_a_launcher_from_before_launches_spoke_still_opens_the_window(self):
        """Its whole message is to connect and hang up."""
        heard = []
        with patch.object(single_instance, "_PIPE_NAME", _unique("Old")):
            running = Listening(steps_aside_for=lambda launch: heard.append(launch) or False)
            try:
                socket = QLocalSocket()
                socket.connectToServer(single_instance._PIPE_NAME)
                self.assertTrue(socket.waitForConnected(3000))
                socket.disconnectFromServer()
                _pump_until(lambda: running.shown)
            finally:
                running.close()

        self.assertEqual((heard, running.shown), ([b""], [True]))

    def test_an_evolver_stepping_aside_answers_no_later_launch(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Gone")):
            running = Listening(steps_aside_for=lambda launch: True)
            try:
                in_the_background(
                    lambda: _ask(single_instance.PREVIEW))
                _pump_until(lambda: running.stepped_aside)
                later = _ask(single_instance.PREVIEW)
            finally:
                running.close()

        self.assertIsNone(later)

    def test_the_listener_is_held_past_the_call_that_made_it(self):
        """A QLocalServer nothing refers to is collected, and the pipe closes
        with it — the handoff would then fail for reasons no log would show."""
        with patch.object(single_instance, "_PIPE_NAME", _unique("Held")):
            running = Listening()
            try:
                self.assertTrue(running.gateway._launches.isListening())
            finally:
                running.close()


class TestTakingOver(unittest.TestCase):
    """What a launch comes to: this process is Evolver now, or it is not."""

    def test_with_nobody_running_the_launch_is_evolver(self):
        with patch.object(single_instance, "_MUTEX_NAME", _unique("FreeMutex")),              patch.object(single_instance, "_PIPE_NAME", _unique("FreePipe")):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.USUAL, end_the_unanswering=False)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)

    def test_an_evolver_that_opens_its_window_keeps_the_launch(self):
        mutex = _unique("ShowMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("ShowPipe")),              held_mutex(mutex):
            running = Listening()
            try:
                outcome = in_the_background(lambda: single_instance.InstanceGateway().take_over(
                    single_instance.USUAL, end_the_unanswering=False))
            finally:
                running.close()

        self.assertEqual(outcome, single_instance.Outcome.HANDED_OFF)
        self.assertEqual(running.shown, [True])

    def test_an_evolver_that_steps_aside_is_waited_out_and_replaced(self):
        mutex = _unique("AsideMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("AsidePipe")),              patch("util.processes.terminate") as terminate,              held_mutex(mutex) as holder:
            running = Listening(steps_aside_for=lambda launch: True)
            running.stepped_aside = _Calls(holder.let_go)
            try:
                outcome = in_the_background(lambda: single_instance.InstanceGateway().take_over(
                    single_instance.PREVIEW, end_the_unanswering=True))
            finally:
                running.close()

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        terminate.assert_not_called()

    def test_an_evolver_that_steps_aside_late_is_still_given_time_to_go(self):
        gateway = single_instance.InstanceGateway()
        answered_at = []

        def ask(_launch, **_):
            if answered_at:
                return None
            time.sleep(0.7)
            answered_at.append(time.monotonic())
            return single_instance.Answer(single_instance.STEPPING_ASIDE, 0)

        def gone():
            return bool(answered_at) and time.monotonic() - answered_at[0] >= 0.6

        with patch.object(single_instance, "_PATIENCE_SECONDS", 1.0),              patch.object(gateway, "ask", side_effect=ask),              patch.object(gateway, "claim", side_effect=gone),              patch("util.processes.terminate") as terminate:
            outcome = gateway.take_over(single_instance.PREVIEW, end_the_unanswering=True)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        terminate.assert_not_called()

    def test_a_preview_ends_an_evolver_that_never_answers(self):
        """One from before launches spoke, or one that has stopped responding: either way
        it holds the work the preview came to take."""
        mutex = _unique("MuteMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("MutePipe")),              patch.object(single_instance, "_PATIENCE_SECONDS", 0.5),              held_mutex(mutex) as holder:
            mute = Unanswering()
            ended = []

            def terminate(pid):
                ended.append(pid)
                holder.let_go()
                return True

            try:
                with patch("util.processes.terminate", side_effect=terminate):
                    outcome = in_the_background(
                        lambda: single_instance.InstanceGateway().take_over(
                            single_instance.PREVIEW, end_the_unanswering=True))
            finally:
                mute.close()

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        self.assertEqual(ended, [os.getpid()])

    def test_an_evolver_ended_when_the_patience_runs_out_is_still_given_time_to_go(self):
        gateway = single_instance.InstanceGateway()
        ended_at = []

        def ask(_launch, *, until):
            if ended_at:
                return None
            time.sleep(max(0.0, until - time.monotonic()))
            return single_instance.Answer(b"", 0)

        def end(_pid):
            ended_at.append(time.monotonic())
            return True

        def gone():
            return bool(ended_at) and time.monotonic() - ended_at[0] >= 0.3

        with patch.object(single_instance, "_PATIENCE_SECONDS", 1.0),              patch.object(gateway, "ask", side_effect=ask),              patch.object(gateway, "claim", side_effect=gone),              patch("util.processes.terminate", side_effect=end):
            outcome = gateway.take_over(single_instance.PREVIEW, end_the_unanswering=True)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)

    def test_the_usual_launch_leaves_an_evolver_that_never_answers_alone(self):
        """The Evolver it reached may simply predate the answers, in which case
        its window has already opened."""
        mutex = _unique("OldMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("OldPipe")),              patch.object(single_instance, "_PATIENCE_SECONDS", 0.5),              held_mutex(mutex):
            mute = Unanswering()
            try:
                with patch("util.processes.terminate") as terminate:
                    outcome = in_the_background(
                        lambda: single_instance.InstanceGateway().take_over(
                            single_instance.USUAL, end_the_unanswering=False))
            finally:
                mute.close()

        self.assertEqual(outcome, single_instance.Outcome.HANDED_OFF)
        terminate.assert_not_called()

    def test_an_evolver_nothing_can_reach_is_given_up_on(self):
        mutex = _unique("DeafMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("DeafPipe")),              patch.object(single_instance, "_PATIENCE_SECONDS", 0.5),              held_mutex(mutex):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

        self.assertEqual(outcome, single_instance.Outcome.UNANSWERED)


REPO_ROOT = Path(__file__).resolve().parents[1]

_STARVED_SECONDS = 2.5

_RUNNING_EVOLVER = """
import sys, time
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from gui import single_instance
single_instance._MUTEX_NAME, single_instance._PIPE_NAME, manner, starved = sys.argv[1:5]
app = QCoreApplication([])
gateway = single_instance.InstanceGateway()
assert gateway.claim()
if manner == "slow to hang up":
    hang_up = QLocalSocket.disconnectFromServer
    def hang_up_slowly(connection):
        time.sleep(float(starved))
        hang_up(connection)
    QLocalSocket.disconnectFromServer = hang_up_slowly
def steps_aside_for(launch):
    if manner == "slow to answer":
        time.sleep(float(starved))
    return launch == single_instance.PREVIEW
if manner == "hangs up without a word":
    mute = QLocalServer()
    assert mute.listen(single_instance._PIPE_NAME)
    mute.newConnection.connect(lambda: mute.nextPendingConnection().disconnectFromServer())
else:
    gateway.serve_launches(steps_aside_for=steps_aside_for,
                           on_show=lambda: None, on_step_aside=app.quit)
print("serving", flush=True)
app.exec()
"""


class TestAcrossProcesses(unittest.TestCase):
    """In life the two ends are two processes, and the claim is let go only
    when the one making way has exited."""

    def _running_evolver(self, mutex: str, pipe: str, manner: str):
        running = subprocess.Popen(
            [sys.executable, "-c", _RUNNING_EVOLVER, mutex, pipe, manner, str(_STARVED_SECONDS)],
            cwd=REPO_ROOT, stdout=subprocess.PIPE,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda: running.poll() is None and running.kill())
        self.assertEqual(running.stdout.readline().strip(), b"serving")
        return running

    def _preview_launch(self, mutex: str, pipe: str):
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", pipe):
            return single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

    def test_an_evolver_that_steps_aside_exits_and_the_preview_is_evolver(self):
        mutex, pipe = _unique("CrossMutex"), _unique("CrossPipe")
        running = self._running_evolver(mutex, pipe, "answers")

        outcome = self._preview_launch(mutex, pipe)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        self.assertEqual(running.wait(timeout=30), 0)

    def test_an_evolver_slow_to_answer_is_waited_for_and_exits_on_its_own(self):
        mutex, pipe = _unique("CrossSlowMutex"), _unique("CrossSlowPipe")
        running = self._running_evolver(mutex, pipe, "slow to answer")

        outcome = self._preview_launch(mutex, pipe)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        self.assertEqual(running.wait(timeout=30), 0)

    def test_an_evolver_slow_to_hang_up_after_stepping_aside_still_exits_on_its_own(self):
        mutex, pipe = _unique("CrossLateMutex"), _unique("CrossLatePipe")
        running = self._running_evolver(mutex, pipe, "slow to hang up")

        outcome = self._preview_launch(mutex, pipe)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        self.assertEqual(running.wait(timeout=30), 0)

    def test_an_evolver_that_never_answers_is_ended_and_the_preview_is_evolver(self):
        mutex, pipe = _unique("CrossMuteMutex"), _unique("CrossMutePipe")
        running = self._running_evolver(mutex, pipe, "hangs up without a word")

        outcome = self._preview_launch(mutex, pipe)

        self.assertEqual(outcome, single_instance.Outcome.CLAIMED)
        self.assertNotEqual(running.wait(timeout=30), 0)


if __name__ == "__main__":
    unittest.main()
