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


if __name__ == "__main__":
    unittest.main()
