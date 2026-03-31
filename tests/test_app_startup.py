"""Smoke test: verify the tray app can be constructed without crashing."""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from gui.app import EvolverApp, _APP_MODEL_ID

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


if __name__ == "__main__":
    unittest.main()
