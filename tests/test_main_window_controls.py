"""Tests for the main window toolbar controls (quit, settings, toggle, next run, run now)."""

import unittest
from datetime import datetime
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox, QToolBar

from gui.main_window import EvolverMainWindow, RunDetailWidget, _summarize_result
from gui.run_record import RunRecord
from gui.toggle_switch import ToggleSwitch

_app = QApplication.instance() or QApplication([])


class TestRunDetailRendering(unittest.TestCase):
    """RunDetailWidget should surface scrape outcomes and the unscraped gap."""

    def _record(self):
        return RunRecord(
            id="2026-06-27T22-18-46", started_at="2026-06-27T22:18:46",
            finished_at="2026-06-27T22:18:46", duration_seconds=699.7,
            trigger="manual", status="error",
            stages=[
                {"name": "metadata", "status": "completed", "duration_seconds": 477.0,
                 "result": {"newly_scraped": 0, "no_scrape_strat": 0,
                            "skipped_unknown_orient": 0, "errors": 58}},
                {"name": "sort", "status": "completed", "duration_seconds": 10.0,
                 "result": {"moved": 103}},
            ],
        )

    def _row_details(self, widget, stage_name):
        for row in range(widget._table.rowCount()):
            if widget._table.item(row, 1).text() == stage_name:
                return widget._table.item(row, 4).text()
        return None

    def test_metadata_row_shows_scraped_and_errors(self):
        widget = RunDetailWidget()
        widget.show_record(self._record())
        details = self._row_details(widget, "metadata")
        self.assertIn("newly_scraped=0", details)
        self.assertIn("errors=58", details)

    def test_info_label_warns_about_unscraped_gap(self):
        widget = RunDetailWidget()
        widget.show_record(self._record())
        self.assertIn("45", widget._info_label.text())


class TestSummarizeResult(unittest.TestCase):
    """Stage detail summaries should make scrape success-vs-error legible."""

    def test_metadata_shows_scraped_and_errors_even_when_zero(self):
        result = {"newly_scraped": 0, "no_scrape_strat": 0,
                  "skipped_unknown_orient": 0, "errors": 58}
        summary = _summarize_result(result, None, "metadata")
        self.assertIn("newly_scraped=0", summary)
        self.assertIn("errors=58", summary)

    def test_other_stages_still_hide_zero_fields(self):
        result = {"moved": 103, "deleted_collisions": 0, "skipped_unknown": 0}
        summary = _summarize_result(result, None, "sort")
        self.assertIn("moved=103", summary)
        self.assertNotIn("deleted_collisions", summary)

    def test_skip_reason_takes_precedence(self):
        summary = _summarize_result(None, "upscale_pending", "verify")
        self.assertEqual(summary, "Reason: upscale_pending")


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
