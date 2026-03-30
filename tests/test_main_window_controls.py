"""Tests for the main window toolbar controls (quit, settings, toggle, next run, run now)."""

import unittest
from datetime import datetime

from PyQt6.QtWidgets import QApplication, QToolBar

from gui.main_window import EvolverMainWindow

_app = QApplication.instance() or QApplication([])


class TestMainWindowToolbarExists(unittest.TestCase):
    """The main window should have a toolbar with all tray-equivalent controls."""

    def setUp(self):
        self.window = EvolverMainWindow()

    def test_has_toolbar(self):
        toolbars = self.window.findChildren(QToolBar)
        self.assertGreaterEqual(len(toolbars), 1)

    def test_has_quit_action(self):
        self.assertIsNotNone(self.window.quit_action)

    def test_has_settings_action(self):
        self.assertIsNotNone(self.window.settings_action)

    def test_has_run_now_action(self):
        self.assertIsNotNone(self.window.run_now_action)

    def test_has_active_toggle(self):
        self.assertIsNotNone(self.window.active_toggle)

    def test_active_toggle_is_checkable(self):
        self.assertTrue(self.window.active_toggle.isCheckable())

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

    def test_next_run_hidden_when_paused(self):
        self.window.update_schedule_status(False, True, None)
        self.assertEqual(self.window._next_run_label.text(), "")

    def test_next_run_hidden_when_running(self):
        self.window.update_schedule_status(True, False, None)
        self.assertEqual(self.window._next_run_label.text(), "")

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


class TestToolbarAppWiring(unittest.TestCase):
    """EvolverApp should wire window toolbar actions the same as tray actions."""

    def test_app_connects_window_toolbar_actions(self):
        from unittest.mock import patch
        from gui.app import EvolverApp

        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()

        # Verify the window toolbar actions are connected by checking
        # that the actions' receivers count is > 0
        self.assertTrue(app._window.quit_action.receivers(app._window.quit_action.triggered) > 0)
        self.assertTrue(app._window.run_now_action.receivers(app._window.run_now_action.triggered) > 0)
        self.assertTrue(app._window.settings_action.receivers(app._window.settings_action.triggered) > 0)
        self.assertTrue(app._window.active_toggle.receivers(app._window.active_toggle.triggered) > 0)


if __name__ == "__main__":
    unittest.main()
