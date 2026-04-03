"""Tests for the main window toolbar controls (quit, settings, toggle, next run, run now)."""

import unittest
from datetime import datetime
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox, QToolBar

from gui.main_window import EvolverMainWindow
from gui.toggle_switch import ToggleSwitch

_app = QApplication.instance() or QApplication([])


class TestMainWindowToolbarExists(unittest.TestCase):
    """The main window should have a toolbar with all tray-equivalent controls."""

    def setUp(self):
        self.window = EvolverMainWindow()

    def test_has_toolbar(self):
        toolbars = self.window.findChildren(QToolBar)
        self.assertGreaterEqual(len(toolbars), 1)

    def test_has_restart_action(self):
        self.assertIsNotNone(self.window.restart_action)

    def test_restart_action_has_icon(self):
        self.assertFalse(self.window.restart_action.icon().isNull())

    def test_has_quit_action(self):
        self.assertIsNotNone(self.window.quit_action)

    def test_has_settings_action(self):
        self.assertIsNotNone(self.window.settings_action)

    def test_has_run_now_action(self):
        self.assertIsNotNone(self.window.run_now_action)

    def test_has_active_toggle(self):
        self.assertIsNotNone(self.window.active_toggle)

    def test_active_toggle_is_toggle_switch(self):
        self.assertIsInstance(self.window.active_toggle, ToggleSwitch)

    def test_active_toggle_starts_checked(self):
        self.assertTrue(self.window.active_toggle.isChecked())


class TestToolbarStateUpdates(unittest.TestCase):
    """update_schedule_status should keep toolbar widgets in sync."""

    def setUp(self):
        self.window = EvolverMainWindow()

    def test_next_run_shown_when_scheduled(self):
        next_run = datetime(2026, 3, 29, 14, 30)
        self.window.update_schedule_status(False, False, next_run)
        self.assertIn("14:30", self.window._next_run_label.text())

    def test_inactive_message_when_paused(self):
        self.window.update_schedule_status(False, True, None)
        self.assertIn("inactive", self.window._next_run_label.text().lower())

    def test_running_message_when_running(self):
        self.window.update_schedule_status(True, False, None)
        self.assertIn("Running", self.window._next_run_label.text())

    def test_run_now_disabled_when_running(self):
        self.window.update_schedule_status(True, False, None)
        self.assertFalse(self.window.run_now_action.isEnabled())

    def test_run_now_enabled_when_idle(self):
        next_run = datetime(2026, 3, 29, 15, 0)
        self.window.update_schedule_status(False, False, next_run)
        self.assertTrue(self.window.run_now_action.isEnabled())

    def test_toggle_unchecked_when_paused(self):
        self.window.update_schedule_status(False, True, None)
        self.assertFalse(self.window.active_toggle.isChecked())

    def test_toggle_checked_when_active(self):
        self.window.update_schedule_status(False, True, None)
        self.window.update_schedule_status(False, False, datetime.now())
        self.assertTrue(self.window.active_toggle.isChecked())

    def test_no_status_bar(self):
        self.assertIsNone(self.window.statusBar().currentMessage() or None)
        # The window should not have a dedicated status bar widget
        self.assertFalse(hasattr(self.window, "_status_bar"))


class TestToggleSwitch(unittest.TestCase):
    """ToggleSwitch custom widget basics."""

    def test_defaults_to_unchecked(self):
        toggle = ToggleSwitch()
        self.assertFalse(toggle.isChecked())

    def test_set_checked(self):
        toggle = ToggleSwitch()
        toggle.setChecked(True)
        self.assertTrue(toggle.isChecked())

    def test_set_checked_false(self):
        toggle = ToggleSwitch(checked=True)
        toggle.setChecked(False)
        self.assertFalse(toggle.isChecked())


class TestQuitConfirmation(unittest.TestCase):
    """Quit button in the window toolbar should prompt for confirmation."""

    def test_quit_proceeds_on_accept(self):
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.QMessageBox") as mock_box:
            mock_box.StandardButton.Yes = QMessageBox.StandardButton.Yes
            mock_box.StandardButton.No = QMessageBox.StandardButton.No
            mock_box.question.return_value = QMessageBox.StandardButton.Yes
            with patch.object(app, "_quit") as mock_quit:
                app._confirm_quit()
                mock_quit.assert_called_once()

    def test_quit_cancelled_on_reject(self):
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        with patch("gui.app.QMessageBox") as mock_box:
            mock_box.StandardButton.Yes = QMessageBox.StandardButton.Yes
            mock_box.StandardButton.No = QMessageBox.StandardButton.No
            mock_box.question.return_value = QMessageBox.StandardButton.No
            with patch.object(app, "_quit") as mock_quit:
                app._confirm_quit()
                mock_quit.assert_not_called()


class TestToolbarAppWiring(unittest.TestCase):
    """EvolverApp should wire window toolbar actions the same as tray actions."""

    def test_app_connects_window_toolbar_actions(self):
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        self.assertTrue(app._window.quit_action.receivers(app._window.quit_action.triggered) > 0)
        self.assertTrue(app._window.run_now_action.receivers(app._window.run_now_action.triggered) > 0)
        self.assertTrue(app._window.settings_action.receivers(app._window.settings_action.triggered) > 0)
        self.assertTrue(app._window.active_toggle.receivers(app._window.active_toggle.clicked) > 0)

    def test_app_connects_window_restart_action(self):
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        self.assertTrue(app._window.restart_action.receivers(app._window.restart_action.triggered) > 0)

    def test_app_connects_tray_restart_action(self):
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        self.assertTrue(app._tray.restart_action.receivers(app._tray.restart_action.triggered) > 0)


if __name__ == "__main__":
    unittest.main()
