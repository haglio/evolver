"""Tests for the crash log, and for the entry point that has to surface one."""

import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

import tray_app
from tests.temp_helpers import workspace_temp_dir
from util import crash_log


@pytest.fixture(autouse=True)
def _the_crash_flag_is_put_back():
    """Give `crash_log._crash_logged` back at the end of every test here.

    Six tests assign that module global directly, and none of them put it back --
    so whatever the last one left was what the rest of the session saw. The
    workaround was visible in the file: `TestWriteCrash` set it to False inline
    before each write, because a neighbour might have left it True. The tests
    still say what they need; nothing now carries it to the next one.
    """
    before = crash_log._crash_logged
    yield
    crash_log._crash_logged = before


class TestInstallExcepthook(unittest.TestCase):
    """install_excepthook must set sys.excepthook to a handler that logs and exits."""

    def setUp(self):
        self._original_hook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self._original_hook

    def test_sets_sys_excepthook(self):
        crash_log.install_excepthook()
        self.assertIsNot(sys.excepthook, self._original_hook)

    def test_hook_writes_crash_log(self):
        crash_log.install_excepthook()
        try:
            raise ValueError("slot went boom")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch.object(crash_log, "write_crash") as mock_write, \
             self.assertRaises(SystemExit):
            sys.excepthook(exc_type, exc_value, exc_tb)

        mock_write.assert_called_once()
        header, detail = mock_write.call_args[0]
        self.assertIn("Qt callback", header)
        self.assertIn("slot went boom", detail)

    def test_hook_exits_with_code_1(self):
        crash_log.install_excepthook()
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch.object(crash_log, "write_crash"), \
             self.assertRaises(SystemExit) as cm:
            sys.excepthook(exc_type, exc_value, exc_tb)

        self.assertEqual(cm.exception.code, 1)


class TestWriteCrash(unittest.TestCase):
    """write_crash must write a timestamped entry to CRASH_LOG."""

    def test_writes_header_and_detail(self):
        with workspace_temp_dir() as tmp_dir:
            tmp = tmp_dir / "tray_crash.log"
            with patch.object(crash_log, "CRASH_LOG", tmp):
                crash_log._crash_logged = False
                crash_log.write_crash("Test header:", "some detail")

            text = tmp.read_text(encoding="utf-8")
            self.assertIn("Test header:", text)
            self.assertIn("some detail", text)
            self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")

    def test_appends_to_existing_content(self):
        """Crash entries must append, not overwrite, so we don't lose evidence."""
        with workspace_temp_dir() as tmp_dir:
            tmp = tmp_dir / "tray_crash.log"
            tmp.write_text("[2026-03-31 10:00:00] Previous entry\n", encoding="utf-8")
            with patch.object(crash_log, "CRASH_LOG", tmp):
                crash_log._crash_logged = False
                crash_log.write_crash("New crash:", "details here")

            content = tmp.read_text(encoding="utf-8")
            self.assertIn("Previous entry", content)
            self.assertIn("New crash:", content)


class TestAtexitHandler(unittest.TestCase):
    """on_exit logs clean exits, unless a crash already explained the ending."""

    def setUp(self):
        crash_log._crash_logged = False

    def test_atexit_writes_when_no_crash(self):
        mock_path = MagicMock()
        mock_path.open = unittest.mock.mock_open()
        with patch.object(crash_log, "CRASH_LOG", mock_path):
            crash_log.on_exit()

        mock_path.open.assert_called_once()
        handle = mock_path.open()
        written = "".join(c.args[0] for c in handle.write.call_args_list)
        self.assertIn("Clean exit", written)

    def test_atexit_includes_stack_trace(self):
        """Clean exit must log a stack trace so we can diagnose what triggered it."""
        with workspace_temp_dir() as tmp_dir:
            tmp = tmp_dir / "tray_crash.log"
            with patch.object(crash_log, "CRASH_LOG", tmp):
                crash_log.on_exit()

            content = tmp.read_text(encoding="utf-8")
            self.assertIn("Clean exit", content)
            # Must contain stack frames showing the call chain
            self.assertIn("on_exit", content)

    def test_atexit_skips_when_crash_already_logged(self):
        crash_log._crash_logged = True
        mock_path = MagicMock()
        with patch.object(crash_log, "CRASH_LOG", mock_path):
            crash_log.on_exit()

        mock_path.open.assert_not_called()

    def test_write_crash_sets_flag(self):
        crash_log._crash_logged = False
        mock_path = MagicMock()
        with patch.object(crash_log, "CRASH_LOG", mock_path):
            crash_log.write_crash("test:", "detail")
        self.assertTrue(crash_log._crash_logged)


class TestWriteInfo(unittest.TestCase):
    """write_info logs without suppressing the atexit handler."""

    def setUp(self):
        crash_log._crash_logged = False

    def test_write_info_does_not_set_crash_flag(self):
        mock_path = MagicMock()
        with patch.object(crash_log, "CRASH_LOG", mock_path):
            crash_log.write_info("Session end:", "detail\n")
        self.assertFalse(crash_log._crash_logged)

    def test_write_info_writes_timestamped_entry(self):
        with workspace_temp_dir() as tmp_dir:
            tmp = tmp_dir / "tray_crash.log"
            with patch.object(crash_log, "CRASH_LOG", tmp):
                crash_log.write_info("Session end:", "detail\n")

            text = tmp.read_text(encoding="utf-8")
            self.assertIn("Session end:", text)
            self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


class TestStartupCrashIsVisible(unittest.TestCase):
    """A crash before the tray icon exists has no window and no stderr to land
    in, so the log alone leaves the user staring at a launcher that did nothing."""

    def test_startup_crash_is_written_to_the_log(self):
        with patch.object(crash_log, "write_crash") as mock_write, \
             patch("tray_app.show_error"):
            tray_app.report_startup_crash("Traceback...\nValueError: no module named x\n")

        mock_write.assert_called_once()
        self.assertIn("startup crash", mock_write.call_args[0][0].lower())

    def test_startup_crash_opens_a_dialog_naming_the_error(self):
        with patch.object(crash_log, "write_crash"), \
             patch("tray_app.show_error") as mock_alert:
            tray_app.report_startup_crash(
                "Traceback...\nModuleNotFoundError: No module named 'qtawesome'\n"
            )

        mock_alert.assert_called_once()
        title, body = mock_alert.call_args[0]
        self.assertIn("evolver", title.lower())
        self.assertIn("qtawesome", body)
        self.assertIn(str(crash_log.CRASH_LOG), body)


if __name__ == "__main__":
    unittest.main()
