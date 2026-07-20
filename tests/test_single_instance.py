"""Tests for single-instance ownership and duplicate-launch handoff."""

import ctypes
import os
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from gui import single_instance

_app = QApplication.instance() or QApplication([])


class TestIsFirstInstance(unittest.TestCase):
    """The mutex must be immune to GetLastError clobbering by injected DLLs
    (e.g. Windhawk)."""

    def test_first_instance_returns_true(self):
        unique = f"TestMutex_{os.getpid()}"
        with patch.object(single_instance, "_MUTEX_NAME", unique):
            self.assertTrue(single_instance.is_first_instance())

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
                self.assertFalse(single_instance.is_first_instance())
        finally:
            kernel32.CloseHandle(h)


class TestRequestShow(unittest.TestCase):
    """A duplicate launch asks the running instance to open its window."""

    def test_returns_false_when_nothing_is_listening(self):
        with patch.object(
            single_instance, "_PIPE_NAME", f"EvolverTest_Absent_{os.getpid()}"
        ):
            self.assertFalse(single_instance.request_show())

    def test_reaches_a_listening_instance_and_triggers_its_callback(self):
        shown = []
        with patch.object(
            single_instance, "_PIPE_NAME", f"EvolverTest_Live_{os.getpid()}"
        ):
            server = single_instance.serve_show_requests(lambda: shown.append(True))
            try:
                self.assertTrue(single_instance.request_show())
                _app.processEvents()
            finally:
                server.close()

        self.assertEqual(shown, [True])


if __name__ == "__main__":
    unittest.main()
