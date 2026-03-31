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
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            tmp = Path(f.name)

        try:
            with patch.object(tray_app, "CRASH_LOG", tmp):
                tray_app._crash_logged = False
                tray_app._write_crash("Test header:", "some detail")

            text = tmp.read_text(encoding="utf-8")
            self.assertIn("Test header:", text)
            self.assertIn("some detail", text)
            self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        finally:
            tmp.unlink()

    def test_appends_to_existing_content(self):
        """Crash entries must append, not overwrite, so we don't lose evidence."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("[2026-03-31 10:00:00] Previous entry\n")
            tmp = Path(f.name)

        try:
            with patch.object(tray_app, "CRASH_LOG", tmp):
                tray_app._crash_logged = False
                tray_app._write_crash("New crash:", "details here")

            content = tmp.read_text(encoding="utf-8")
            self.assertIn("Previous entry", content)
            self.assertIn("New crash:", content)
        finally:
            tmp.unlink()


class TestAtexitHandler(unittest.TestCase):
    """_install_atexit registers a handler that logs clean exits."""

    def setUp(self):
        tray_app._crash_logged = False

    def test_atexit_writes_when_no_crash(self):
        mock_path = MagicMock()
        mock_path.open = unittest.mock.mock_open()
        with patch.object(tray_app, "CRASH_LOG", mock_path):
            tray_app._on_exit()

        mock_path.open.assert_called_once()
        handle = mock_path.open()
        written = "".join(c.args[0] for c in handle.write.call_args_list)
        self.assertIn("Clean exit", written)

    def test_atexit_includes_stack_trace(self):
        """Clean exit must log a stack trace so we can diagnose what triggered it."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            tmp = Path(f.name)

        try:
            with patch.object(tray_app, "CRASH_LOG", tmp):
                tray_app._on_exit()

            content = tmp.read_text(encoding="utf-8")
            self.assertIn("Clean exit", content)
            # Must contain stack frames showing the call chain
            self.assertIn("_on_exit", content)
        finally:
            tmp.unlink()

    def test_atexit_appends_to_existing_content(self):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("[2026-03-31 10:00:00] Previous crash entry\n")
            tmp = Path(f.name)

        try:
            with patch.object(tray_app, "CRASH_LOG", tmp):
                tray_app._on_exit()

            content = tmp.read_text(encoding="utf-8")
            self.assertIn("Previous crash entry", content)
            self.assertIn("Clean exit", content)
        finally:
            tmp.unlink()

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
