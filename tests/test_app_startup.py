"""Smoke test: verify the tray app can be constructed without crashing."""

import ctypes
import os
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from gui.app import EvolverApp, _APP_MODEL_ID, _acquire_single_instance_mutex

_app = QApplication.instance() or QApplication([])


class TestAppStartup(unittest.TestCase):

    def test_evolver_app_constructs_without_error(self):
        # Patch QApplication creation since we already have one
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()
        # Tray, window, and scheduler should all exist
        self.assertIsNotNone(app._tray)
        self.assertIsNotNone(app._window)
        self.assertIsNotNone(app._scheduler)

    def test_app_window_icon_matches_tray_icon(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()
        # Taskbar icon should be set to the same icon as the tray
        app_icon = app._app.windowIcon()
        self.assertFalse(app_icon.isNull(), "Application window icon should be set")

    @patch("gui.app.ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID")
    def test_app_sets_appusermodelid(self, mock_set_id):
        with patch("gui.app.QApplication", return_value=_app):
            EvolverApp()
        mock_set_id.assert_called_once_with(_APP_MODEL_ID)


class TestNonAiUpscaleToggle(unittest.TestCase):
    """The tray menu's opt-in switch for the multi-hour non-AI encodes."""

    def _app_with_fresh_settings(self):
        from gui.settings import EvolverSettings
        with patch("gui.app.QApplication", return_value=_app), \
             patch("gui.app.EvolverSettings.load", return_value=EvolverSettings()):
            return EvolverApp()

    def test_tray_toggle_starts_unchecked_by_default(self):
        app = self._app_with_fresh_settings()
        self.assertTrue(app._tray.nonai_action.isCheckable())
        self.assertFalse(app._tray.nonai_action.isChecked())

    def test_toggling_flips_and_saves_the_setting(self):
        app = self._app_with_fresh_settings()
        with patch("gui.app.EvolverSettings.save") as mock_save:
            app._tray.nonai_action.trigger()
        self.assertTrue(app._settings.nonai_upscale_enabled)
        mock_save.assert_called_once()

    def test_worker_receives_the_toggle_state(self):
        app = self._app_with_fresh_settings()
        app._settings.nonai_upscale_enabled = True
        with patch("gui.app.PipelineWorker") as mock_worker:
            app._start_run("manual")
        self.assertTrue(mock_worker.call_args.kwargs["nonai_enabled"])


class TestSessionManagement(unittest.TestCase):
    """EvolverApp must log Windows session-management events that could kill it."""

    def test_connects_to_commit_data_request(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()
        # The commitDataRequest signal should have our handler connected
        self.assertTrue(
            hasattr(app, "_on_session_end"),
            "EvolverApp must have a _on_session_end handler",
        )

    def test_session_end_logs_to_crash_log(self):
        import tray_app

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        mock_manager = unittest.mock.MagicMock()
        with patch.object(tray_app, "_write_info") as mock_write:
            app._on_session_end(mock_manager)

        mock_write.assert_called_once()
        header = mock_write.call_args[0][0]
        self.assertIn("session", header.lower())

    def test_session_end_quits_app(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        mock_manager = unittest.mock.MagicMock()
        with patch.object(app, "_quit") as mock_quit, \
             patch("gui.app.tray_app._write_info"):
            app._on_session_end(mock_manager)

        mock_quit.assert_called_once()


class TestRestart(unittest.TestCase):
    """_restart() should spawn a new process and quit the current one."""

    def test_restart_spawns_process_and_quits(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit") as mock_quit:
            app._restart()
            mock_popen.assert_called_once()
            mock_quit.assert_called_once()

    def test_restart_launches_tray_app(self):
        import config

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"):
            app._restart()
            args = mock_popen.call_args[0][0]
            self.assertEqual(args[1], str(config.PROJECT_DIR / "tray_app.py"))

    def test_restart_passes_show_window_when_window_visible(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow"):
            app._restart()
            args = mock_popen.call_args[0][0]
            self.assertIn("--show-window", args)

    def test_restart_omits_show_window_when_window_hidden(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=False):
            app._restart()
            args = mock_popen.call_args[0][0]
            self.assertNotIn("--show-window", args)

    def test_restart_grants_foreground_to_child_when_window_visible(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        mock_proc = unittest.mock.MagicMock()
        mock_proc.pid = 12345
        with patch("gui.app.subprocess.Popen", return_value=mock_proc), \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=True), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_called_once_with(12345)

    def test_restart_skips_foreground_grant_when_window_hidden(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.subprocess.Popen"), \
             patch.object(app, "_quit"), \
             patch.object(app._window, "isVisible", return_value=False), \
             patch("gui.app.ctypes.windll.user32.AllowSetForegroundWindow") as mock_allow:
            app._restart()
            mock_allow.assert_not_called()


class TestDuplicateInstanceLogging(unittest.TestCase):
    """When a second instance is rejected by the mutex, the log must say so."""

    def test_duplicate_instance_logs_specific_message(self):
        import tray_app

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app._acquire_single_instance_mutex", return_value=False), \
             patch.object(app._tray, "showMessage"), \
             patch.object(tray_app, "_write_crash") as mock_write:
            app.run()

        mock_write.assert_called_once()
        header = mock_write.call_args[0][0]
        self.assertIn("already running", header.lower())


class TestShowWindowFlag(unittest.TestCase):
    """--show-window should open the main window on startup."""

    def test_run_shows_window_when_flag_present(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch.object(app, "_show_window") as mock_show, \
             patch("gui.app._acquire_single_instance_mutex", return_value=True), \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py", "--show-window"]
            app.run()
            mock_show.assert_called_once()

    def test_run_does_not_show_window_without_flag(self):
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch.object(app, "_show_window") as mock_show, \
             patch("gui.app._acquire_single_instance_mutex", return_value=True), \
             patch.object(app._tray, "show"), \
             patch.object(app._scheduler, "start"), \
             patch.object(app._app, "exec", return_value=0), \
             patch("gui.app.sys") as mock_sys:
            mock_sys.argv = ["tray_app.py"]
            app.run()
            mock_show.assert_not_called()


class TestSingleInstanceMutex(unittest.TestCase):
    """Verify the single-instance mutex works correctly and is immune to
    GetLastError clobbering by injected DLLs (e.g. Windhawk)."""

    def test_first_instance_returns_true(self):
        unique = f"TestMutex_{os.getpid()}"
        with patch("gui.app._MUTEX_NAME", unique):
            self.assertTrue(_acquire_single_instance_mutex())

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
            with patch("gui.app._MUTEX_NAME", unique):
                self.assertFalse(_acquire_single_instance_mutex())
        finally:
            kernel32.CloseHandle(h)



if __name__ == "__main__":
    unittest.main()
