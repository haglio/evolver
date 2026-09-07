"""Tests for single-instance ownership and duplicate-launch handoff."""
from __future__ import annotations

import ctypes
import os
import time
import unittest
from unittest.mock import patch

from gui import single_instance
from tests.gui_support import QAPP


class TestIsFirstInstance(unittest.TestCase):
    """The mutex must be immune to GetLastError clobbering by injected DLLs
    (e.g. Windhawk)."""

    def test_first_instance_returns_true(self):
        unique = f"TestMutex_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique):
            self.assertTrue(single_instance.InstanceGateway().claim())

    def test_second_instance_returns_false(self):
        unique = f"TestMutex_Dup_{os.getpid()}"
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        h = kernel32.CreateMutexW(None, False, unique)
        self.assertTrue(h, "Setup: CreateMutexW should succeed")
        try:
            with patch.object(single_instance, "_MUTEX_NAME", unique):
                self.assertFalse(single_instance.InstanceGateway().claim())
        finally:
            kernel32.CloseHandle(h)


def _pump_until(condition, deadline_seconds: float = 10.0) -> bool:
    """Spin the shared event loop until *condition* holds, or the deadline passes."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        QAPP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class TestRequestShow(unittest.TestCase):
    """A duplicate launch asks the running instance to open its window."""

    def test_returns_false_when_nothing_is_listening(self):
        with patch.object(
            single_instance, "_PIPE_NAME", f"EvolverTest_Absent_{os.getpid()}"
        ):
            self.assertFalse(single_instance.InstanceGateway().hand_off())

    def test_reaches_a_listening_instance_and_triggers_its_callback(self):
        shown = []
        with patch.object(
            single_instance, "_PIPE_NAME", f"EvolverTest_Live_{os.getpid()}"
        ):
            listener = single_instance.InstanceGateway()
            listener.serve_show_requests(lambda: shown.append(True))
            try:
                self.assertTrue(single_instance.InstanceGateway().hand_off())
                _pump_until(lambda: shown)
            finally:
                listener._show_requests.close()

        self.assertEqual(shown, [True])

    def test_the_listener_is_held_past_the_call_that_made_it(self):
        """A QLocalServer nothing refers to is collected, and the pipe closes
        with it — the handoff would then fail for reasons no log would show."""
        gateway = single_instance.InstanceGateway()
        with patch.object(
            single_instance, "_PIPE_NAME", f"EvolverTest_Held_{os.getpid()}"
        ):
            gateway.serve_show_requests(lambda: None)
            try:
                self.assertTrue(gateway._show_requests.isListening())
            finally:
                gateway._show_requests.close()


if __name__ == "__main__":
    unittest.main()
