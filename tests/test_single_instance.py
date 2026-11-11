from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app_support.testing import process_terminated
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from gui import run_controller, single_instance
from gui.single_instance import Answer
from tests.gui_support import QAPP


class TestIsFirstInstance(unittest.TestCase):
    def test_the_claim_and_pipe_names_never_change(self):
        assert (single_instance._MUTEX_NAME, single_instance._PIPE_NAME) == (
            "EvolverTrayApp_SingleInstance", "EvolverTrayApp_ShowWindow"), (
            "an Evolver started before a change is neither refused by one started after it "
            "nor reachable by its launches")

    def test_a_mutex_windows_would_not_make_is_a_refusal_to_run(self):
        with patch("gui.single_instance.try_acquire_mutex", return_value=None):
            assert not single_instance.InstanceGateway().claim()

    def test_the_first_evolver_to_ask_is_given_the_claim(self):
        unique = f"TestMutex_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique):
            assert single_instance.InstanceGateway().claim()

    def test_letting_go_frees_the_claim_while_this_process_lives_on(self):
        with patch.object(single_instance, "_MUTEX_NAME", _unique("LetGoMutex")),              patch.object(single_instance, "_PIPE_NAME", _unique("LetGoPipe")):
            holder = single_instance.InstanceGateway()
            assert holder.claim()
            assert not single_instance.InstanceGateway().claim()

            holder.let_go()

            assert single_instance.InstanceGateway().claim()

    def test_a_second_evolver_is_refused(self):
        unique = f"TestMutex_Dup_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique), held_mutex(unique):
            assert not single_instance.InstanceGateway().claim(), (
                "two Evolvers run two pipelines over one library, and two presence polls "
                "freeze the one encode twice and thaw it once")


_A_STARVED_EVOLVERS_SLOWEST_ANSWER_SECONDS = 15.0


class held_mutex:
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
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        QAPP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _unique(label: str) -> str:
    return f"EvolverTest_{label}_{os.getpid()}_{time.monotonic_ns()}"


def _ask(launch: bytes) -> Answer | None:
    return single_instance.InstanceGateway().ask(launch, until=time.monotonic() + 10.0)


class Listening:
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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


REPO_ROOT = Path(__file__).resolve().parents[1]

_STARVED_SECONDS = 2.5

_ANSWERS_BEFORE_HEARING = r"""
import ctypes, sys, time
pipe_name, reply, heard_length = sys.argv[1], sys.argv[2].encode(), int(sys.argv[3])
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
handle, number = ctypes.c_void_p, ctypes.c_uint32
kernel32.CreateNamedPipeW.argtypes = [ctypes.c_wchar_p, *[number] * 6, handle]
kernel32.CreateNamedPipeW.restype = handle
kernel32.ConnectNamedPipe.argtypes = [handle, handle]
kernel32.FlushFileBuffers.argtypes = [handle]
kernel32.DisconnectNamedPipe.argtypes = [handle]
kernel32.CloseHandle.argtypes = [handle]
kernel32.WriteFile.argtypes = [handle, ctypes.c_char_p, number, ctypes.POINTER(number), handle]
kernel32.ReadFile.argtypes = kernel32.WriteFile.argtypes
duplex, one_instance, unbuffered = 3, 1, 0
pipe = kernel32.CreateNamedPipeW("\\\\.\\pipe\\" + pipe_name, duplex, 0, one_instance,
                                 unbuffered, unbuffered, 0, None)
assert pipe not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
print("serving", flush=True)
moved = number()
heard = ctypes.create_string_buffer(heard_length)
kernel32.ConnectNamedPipe(pipe, None)
kernel32.WriteFile(pipe, reply, len(reply), ctypes.byref(moved), None)
time.sleep(0.1)
kernel32.ReadFile(pipe, heard, heard_length, ctypes.byref(moved), None)
kernel32.FlushFileBuffers(pipe)
kernel32.DisconnectNamedPipe(pipe)
kernel32.CloseHandle(pipe)
"""

_RUNNING_EVOLVER = """
import os, sys, time
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from gui import single_instance
from gui.single_instance import Answer
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
    def step_aside():
        print("stepped aside", flush=True)
        if manner != "lingers after stepping aside":
            app.quit()
    gateway.serve_launches(steps_aside_for=steps_aside_for,
                           on_show=lambda: print("shown", flush=True), on_step_aside=step_aside)
print("serving", os.getpid(), flush=True)
app.exec()
"""


def _running_evolver(test: unittest.TestCase, mutex: str, pipe: str, manner: str) -> subprocess.Popen:
    running = subprocess.Popen(
        [sys.executable, "-c", _RUNNING_EVOLVER, mutex, pipe, manner, str(_STARVED_SECONDS)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        creationflags=subprocess.CREATE_NO_WINDOW)
    test.addCleanup(lambda: running.poll() is None and running.kill())
    serving, pid = running.stdout.readline().split()
    assert serving == b"serving"
    running.evolver_pid = int(pid)
    return running


def _answering_before_hearing(test: unittest.TestCase, pipe: str, reply: bytes,
                              heard: bytes) -> subprocess.Popen:
    running = subprocess.Popen(
        [sys.executable, "-c", _ANSWERS_BEFORE_HEARING, pipe, reply.decode(), str(len(heard))],
        stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    test.addCleanup(lambda: running.poll() is None and running.kill())
    assert running.stdout.readline().strip() == b"serving"
    return running


def _what_it_did(running: subprocess.Popen) -> list[str]:
    first = running.stdout.readline()
    running.kill()
    rest, _ = running.communicate(timeout=30)
    return [line.strip() for line in (first + rest).decode().splitlines()]


class TestAskingTheRunningOne(unittest.TestCase):
    def test_nothing_listening_is_no_answer(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Absent")):
            assert _ask(single_instance.USUAL) is None

    def test_the_running_one_says_it_steps_aside_and_which_process_it_is(self):
        pipe = _unique("Aside")
        running = _running_evolver(self, _unique("AsideMutex"), pipe, "answers")
        with patch.object(single_instance, "_PIPE_NAME", pipe):
            answer = _ask(single_instance.PREVIEW)

        assert answer == Answer(single_instance.STEPPING_ASIDE, running.evolver_pid)
        assert _what_it_did(running) == ["stepped aside"]

    def test_a_launch_it_does_not_step_aside_for_opens_its_window(self):
        pipe = _unique("Show")
        running = _running_evolver(self, _unique("ShowMutex"), pipe, "answers")
        with patch.object(single_instance, "_PIPE_NAME", pipe):
            answer = _ask(single_instance.USUAL)

        assert answer.reply == single_instance.SHOWING
        assert _what_it_did(running) == ["shown"]

    def test_an_answer_in_before_the_launch_has_finished_speaking_is_heard(self):
        pipe = _unique("Early")
        running = _answering_before_hearing(self, pipe, single_instance.STEPPING_ASIDE,
                                            heard=single_instance.PREVIEW)
        with patch.object(single_instance, "_PIPE_NAME", pipe):
            answer = _ask(single_instance.PREVIEW)
        assert running.wait(timeout=30) == 0

        assert answer.reply == single_instance.STEPPING_ASIDE

    def test_a_launcher_from_before_launches_spoke_still_opens_the_window(self):
        heard = []
        with patch.object(single_instance, "_PIPE_NAME", _unique("Old")):
            running = Listening(steps_aside_for=lambda launch: heard.append(launch) or False)
            try:
                socket = QLocalSocket()
                socket.connectToServer(single_instance._PIPE_NAME)
                assert socket.waitForConnected(3000)
                socket.disconnectFromServer()
                _pump_until(lambda: running.shown)
            finally:
                running.close()

        assert (heard, running.shown) == ([b""], [True])

    def test_an_evolver_stepping_aside_answers_no_later_launch(self):
        pipe = _unique("Gone")
        running = _running_evolver(self, _unique("GoneMutex"), pipe, "lingers after stepping aside")
        with patch.object(single_instance, "_PIPE_NAME", pipe):
            _ask(single_instance.PREVIEW)
            assert running.stdout.readline().strip() == b"stepped aside"
            later = _ask(single_instance.PREVIEW)

        assert later is None

    def test_a_pipe_that_cannot_listen_is_logged_not_shown(self):
        never_listening = QLocalServer()
        gateway = single_instance.InstanceGateway()

        with (patch("gui.single_instance.running_copy.listen", return_value=never_listening),
              self.assertLogs("gui.single_instance", "ERROR") as logged):
            gateway.serve_launches(steps_aside_for=lambda launch: False,
                                   on_show=lambda: None, on_step_aside=lambda: None)

        assert single_instance._PIPE_NAME in logged.output[0]
        assert gateway._launches is never_listening

    def test_the_listener_is_held_past_the_call_that_made_it(self):
        with patch.object(single_instance, "_PIPE_NAME", _unique("Held")):
            running = Listening()
            try:
                assert running.gateway._launches.isListening()
            finally:
                running.close()


class TestTakingOver(unittest.TestCase):
    def test_patience_outlasts_a_starved_answer_and_the_stages_grace(self):
        assert single_instance._PATIENCE_SECONDS > (
            _A_STARVED_EVOLVERS_SLOWEST_ANSWER_SECONDS + run_controller.STAGE_GRACE_SECONDS)

    def test_with_nobody_running_the_launch_is_evolver(self):
        with patch.object(single_instance, "_MUTEX_NAME", _unique("FreeMutex")),              patch.object(single_instance, "_PIPE_NAME", _unique("FreePipe")):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.USUAL, end_the_unanswering=False)

        assert outcome == single_instance.Outcome.CLAIMED

    def test_an_evolver_that_opens_its_window_keeps_the_launch(self):
        mutex, pipe = _unique("ShowMutex"), _unique("ShowPipe")
        running = _running_evolver(self, mutex, pipe, "answers")
        with patch.object(single_instance, "_MUTEX_NAME", mutex), \
             patch.object(single_instance, "_PIPE_NAME", pipe):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.USUAL, end_the_unanswering=False)

        assert outcome == single_instance.Outcome.HANDED_OFF
        assert _what_it_did(running) == ["shown"]

    def test_an_evolver_that_steps_aside_is_waited_out_and_replaced(self):
        mutex, pipe = _unique("AsideMutex"), _unique("AsidePipe")
        _running_evolver(self, mutex, pipe, "answers")
        with patch.object(single_instance, "_MUTEX_NAME", mutex), \
             patch.object(single_instance, "_PIPE_NAME", pipe), \
             process_terminated() as terminate:
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

        assert outcome == single_instance.Outcome.CLAIMED
        terminate.assert_not_called()

    def test_an_evolver_that_steps_aside_late_is_still_given_time_to_go(self):
        gateway = single_instance.InstanceGateway()
        clock = FakeClock()
        answered_at = []

        def ask(_launch, **_):
            if answered_at:
                return None
            clock.sleep(0.7)
            answered_at.append(clock.monotonic())
            return single_instance.Answer(single_instance.STEPPING_ASIDE, 0)

        def gone():
            return bool(answered_at) and clock.monotonic() - answered_at[0] >= 0.6

        with patch.object(single_instance, "time", clock), \
             patch.object(single_instance, "_PATIENCE_SECONDS", 1.0), \
             patch.object(gateway, "ask", side_effect=ask), \
             patch.object(gateway, "claim", side_effect=gone), \
             process_terminated() as terminate:
            outcome = gateway.take_over(single_instance.PREVIEW, end_the_unanswering=True)

        assert outcome == single_instance.Outcome.CLAIMED
        terminate.assert_not_called()

    def test_a_preview_ends_an_evolver_that_never_answers(self):
        mutex, pipe = _unique("MuteMutex"), _unique("MutePipe")
        running = _running_evolver(self, mutex, pipe, "hangs up without a word")
        ended = []

        def terminate(pid):
            ended.append(pid)
            running.kill()
            running.wait(timeout=30)
            return True

        with patch.object(single_instance, "_MUTEX_NAME", mutex), \
             patch.object(single_instance, "_PIPE_NAME", pipe), \
             process_terminated(side_effect=terminate):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

        assert outcome == single_instance.Outcome.CLAIMED
        assert ended == [running.evolver_pid]

    def test_an_evolver_ended_when_the_patience_runs_out_is_still_given_time_to_go(self):
        gateway = single_instance.InstanceGateway()
        clock = FakeClock()
        ended_at = []

        def ask(_launch, *, until):
            if ended_at:
                return None
            clock.sleep(max(0.0, until - clock.monotonic()))
            return single_instance.Answer(b"", 0)

        def end(_pid):
            ended_at.append(clock.monotonic())
            return True

        def gone():
            return bool(ended_at) and clock.monotonic() - ended_at[0] >= 0.3

        with patch.object(single_instance, "time", clock), \
             patch.object(single_instance, "_PATIENCE_SECONDS", 1.0), \
             patch.object(gateway, "ask", side_effect=ask), \
             patch.object(gateway, "claim", side_effect=gone), \
             process_terminated(side_effect=end):
            outcome = gateway.take_over(single_instance.PREVIEW, end_the_unanswering=True)

        assert outcome == single_instance.Outcome.CLAIMED

    def test_the_usual_launch_leaves_an_evolver_that_never_answers_alone(self):
        mutex, pipe = _unique("OldMutex"), _unique("OldPipe")
        _running_evolver(self, mutex, pipe, "hangs up without a word")
        with patch.object(single_instance, "_MUTEX_NAME", mutex), \
             patch.object(single_instance, "_PIPE_NAME", pipe), \
             process_terminated() as terminate:
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.USUAL, end_the_unanswering=False)

        assert outcome == single_instance.Outcome.HANDED_OFF, (
            "an Evolver that never answers predates the answers and opened its window on the connection")
        terminate.assert_not_called()

    def test_an_evolver_nothing_can_reach_is_given_up_on(self):
        mutex = _unique("DeafMutex")
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", _unique("DeafPipe")),              patch.object(single_instance, "_PATIENCE_SECONDS", 0.5),              held_mutex(mutex):
            outcome = single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

        assert outcome == single_instance.Outcome.UNANSWERED


class TestBecomingEvolver(unittest.TestCase):
    def _launch(self, *, as_preview=False, only_if_not_running=False, claimed=False,
                outcome=single_instance.Outcome.HANDED_OFF):
        gateway = single_instance.InstanceGateway()
        with patch.object(gateway, "claim", return_value=claimed) as claim, \
             patch.object(gateway, "take_over", return_value=outcome) as take_over, \
             patch("util.crash_log.write_info") as logged:
            came_to = gateway.become_evolver(as_preview=as_preview,
                                             only_if_not_running=only_if_not_running)
        return came_to, claim, take_over, logged

    def test_the_usual_launch_hands_itself_to_the_running_evolver(self):
        came_to, _claim, take_over, logged = self._launch()

        take_over.assert_called_once_with(single_instance.USUAL, end_the_unanswering=False)
        assert came_to == single_instance.Outcome.HANDED_OFF
        assert "already running" in logged.call_args.args[0].lower()
        assert "duplicate launch" in logged.call_args.args[1]

    def test_a_preview_takes_the_work_over_and_ends_an_evolver_that_will_not_answer(self):
        _came_to, _claim, take_over, _logged = self._launch(as_preview=True)

        take_over.assert_called_once_with(single_instance.PREVIEW, end_the_unanswering=True)

    def test_a_launch_that_is_evolver_now_logs_nothing(self):
        came_to, _claim, _take_over, logged = self._launch(
            outcome=single_instance.Outcome.CLAIMED)

        assert came_to == single_instance.Outcome.CLAIMED
        logged.assert_not_called()

    def test_a_start_for_when_evolver_is_not_running_claims_without_asking_the_running_one(self):
        came_to, _claim, take_over, logged = self._launch(only_if_not_running=True, claimed=True)

        assert came_to == single_instance.Outcome.CLAIMED
        take_over.assert_not_called()
        logged.assert_not_called()

    def test_a_start_for_when_evolver_is_not_running_leaves_a_running_one_as_it_was(self):
        came_to, _claim, take_over, logged = self._launch(only_if_not_running=True, claimed=False)

        assert came_to == single_instance.Outcome.LEFT_AS_IT_WAS
        take_over.assert_not_called()
        header, detail = logged.call_args.args
        assert "already running" in header.lower()
        assert single_instance.IF_NOT_RUNNING in detail


class TestTheClaimPassesWhenItsHolderExits(unittest.TestCase):
    def _running_evolver(self, mutex: str, pipe: str, manner: str):
        return _running_evolver(self, mutex, pipe, manner)

    def _preview_launch(self, mutex: str, pipe: str):
        with patch.object(single_instance, "_MUTEX_NAME", mutex),              patch.object(single_instance, "_PIPE_NAME", pipe):
            return single_instance.InstanceGateway().take_over(
                single_instance.PREVIEW, end_the_unanswering=True)

    def test_an_evolver_that_steps_aside_exits_and_the_preview_is_evolver(self):
        mutex, pipe = _unique("CrossMutex"), _unique("CrossPipe")
        running = self._running_evolver(mutex, pipe, "answers")

        outcome = self._preview_launch(mutex, pipe)

        assert outcome == single_instance.Outcome.CLAIMED
        assert running.wait(timeout=30) == 0

    def test_an_evolver_slow_to_answer_is_waited_for_and_exits_on_its_own(self):
        mutex, pipe = _unique("CrossSlowMutex"), _unique("CrossSlowPipe")
        running = self._running_evolver(mutex, pipe, "slow to answer")

        outcome = self._preview_launch(mutex, pipe)

        assert outcome == single_instance.Outcome.CLAIMED
        assert running.wait(timeout=30) == 0

    def test_an_evolver_slow_to_hang_up_after_stepping_aside_still_exits_on_its_own(self):
        mutex, pipe = _unique("CrossLateMutex"), _unique("CrossLatePipe")
        running = self._running_evolver(mutex, pipe, "slow to hang up")

        outcome = self._preview_launch(mutex, pipe)

        assert outcome == single_instance.Outcome.CLAIMED
        assert running.wait(timeout=30) == 0

    def test_an_evolver_that_never_answers_is_ended_and_the_preview_is_evolver(self):
        mutex, pipe = _unique("CrossMuteMutex"), _unique("CrossMutePipe")
        running = self._running_evolver(mutex, pipe, "hangs up without a word")

        outcome = self._preview_launch(mutex, pipe)

        assert outcome == single_instance.Outcome.CLAIMED
        assert running.wait(timeout=30) != 0


if __name__ == "__main__":
    unittest.main()
