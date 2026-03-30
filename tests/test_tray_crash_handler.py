"""Tests for tray_app crash handling: excepthook, BaseException, exit logging."""

import sys
import unittest
from unittest.mock import patch, MagicMock

import tray_app


class TestInstallExcepthook(unittest.TestCase):
    """_install_excepthook must set sys.excepthook to a handler that logs and exits."""

    def setUp(self):
        self._original_hook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self._original_hook

    def test_sets_sys_excepthook(self):
        tray_app._install_excepthook()
        self.assertIsNot(sys.excepthook, self._original_hook)

    def test_hook_writes_crash_log(self):
        tray_app._install_excepthook()
        try:
            raise ValueError("slot went boom")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch.object(tray_app, "_write_crash") as mock_write, \
             self.assertRaises(SystemExit):
            sys.excepthook(exc_type, exc_value, exc_tb)

        mock_write.assert_called_once()
        header, detail = mock_write.call_args[0]
        self.assertIn("Qt callback", header)
        self.assertIn("slot went boom", detail)

    def test_hook_exits_with_code_1(self):
        tray_app._install_excepthook()
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch.object(tray_app, "_write_crash"), \
             self.assertRaises(SystemExit) as cm:
            sys.excepthook(exc_type, exc_value, exc_tb)

        self.assertEqual(cm.exception.code, 1)


class TestWriteCrash(unittest.TestCase):
    """_write_crash must write a timestamped entry to CRASH_LOG."""

    def test_writes_header_and_detail(self):
        mock_path = MagicMock()
        with patch.object(tray_app, "CRASH_LOG", mock_path):
            tray_app._write_crash("Test header:", "some detail")

        mock_path.write_text.assert_called_once()
        text = mock_path.write_text.call_args[0][0]
        self.assertIn("Test header:", text)
        self.assertIn("some detail", text)
        self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


class TestAtexitHandler(unittest.TestCase):
    """_install_atexit registers a handler that logs clean exits."""

    def setUp(self):
        tray_app._crash_logged = False

    def test_atexit_writes_when_no_crash(self):
        mock_path = MagicMock()
        with patch.object(tray_app, "CRASH_LOG", mock_path):
            tray_app._on_exit()

        mock_path.write_text.assert_called_once()
        text = mock_path.write_text.call_args[0][0]
        self.assertIn("Clean exit", text)

    def test_atexit_skips_when_crash_already_logged(self):
        tray_app._crash_logged = True
        mock_path = MagicMock()
        with patch.object(tray_app, "CRASH_LOG", mock_path):
            tray_app._on_exit()

        mock_path.write_text.assert_not_called()

    def test_write_crash_sets_flag(self):
        tray_app._crash_logged = False
        mock_path = MagicMock()
        with patch.object(tray_app, "CRASH_LOG", mock_path):
            tray_app._write_crash("test:", "detail")
        self.assertTrue(tray_app._crash_logged)


if __name__ == "__main__":
    unittest.main()
