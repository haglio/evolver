"""Tests for the main window toolbar controls (quit, settings, toggle, next run, run now)."""

import unittest
from datetime import datetime
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication, QMessageBox, QToolBar

from gui.main_window import EvolverMainWindow, RunDetailWidget, _summarize_result
from gui.run_record import RunRecord
from gui.toggle_switch import ToggleSwitch

_app = QApplication.instance() or QApplication([])


class TestRunDetailRendering(unittest.TestCase):
    """RunDetailWidget should surface scrape successes alongside errors."""

    def _record(self):
        return RunRecord(
            id="2026-06-27T22-18-46", started_at="2026-06-27T22:18:46",
            finished_at="2026-06-27T22:18:46", duration_seconds=699.7,
            trigger="manual", status="error",
            stages=[
                {"name": "metadata", "status": "completed", "duration_seconds": 477.0,
                 "result": {"newly_scraped": 0, "already_scraped": 0,
                            "skipped_failed": 0, "no_scrape_strat": 0, "errors": 58}},
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


class TestRunHistoryMarks(unittest.TestCase):
    """A run's verdict is its mark's color, never the whole line's."""

    def _item(self, status):
        record = RunRecord(
            id="2026-07-25T15-20-02", started_at="2026-07-25T15:20:02",
            finished_at="2026-07-25T15:20:02", duration_seconds=12.0,
            trigger="scheduled", status=status, stages=[],
        )
        self.window = EvolverMainWindow()
        with patch("gui.main_window.load_runs", return_value=[record]):
            self.window.refresh_history()
        return self.window._history_list.item(0)

    def test_a_failed_run_leaves_its_timestamp_the_default_color(self):
        """Reddening the timestamp too made the line shout without saying why."""
        item = self._item("error")
        self.assertEqual(item.foreground().style(), Qt.BrushStyle.NoBrush)

    def test_a_failed_run_carries_the_cross_as_its_icon(self):
        self.assertFalse(self._item("error").icon().isNull())

    def test_the_label_itself_is_just_the_time_and_duration(self):
        self.assertEqual(self._item("success").text(), "2026/07/25 08:20 (12s)")


class TestStageStatusColumn(unittest.TestCase):
    """The Status column is a symbol, and only the symbol carries the color."""

    def _status_cell(self, status):
        record = RunRecord(
            id="2026-07-25T15-20-02", started_at="2026-07-25T15:20:02",
            finished_at="2026-07-25T15:20:02", duration_seconds=12.0,
            trigger="scheduled", status="error",
            stages=[{"name": "upscale_non_ai", "status": status,
                     "duration_seconds": 1.0, "result": None}],
        )
        # Held on self: a local would be collected, taking the table's C++
        # items with it before the assertions can read them.
        self.widget = RunDetailWidget()
        self.widget.show_record(record)
        return self.widget._table.item(0, 2)

    def test_a_completed_stage_shows_a_green_check(self):
        cell = self._status_cell("completed")
        self.assertEqual(cell.text(), "✔")
        self.assertEqual(cell.foreground().color().name(), "#30a030")

    def test_an_errored_stage_shows_a_red_cross(self):
        """The row a low-disk hold now produces, which no run record had before."""
        cell = self._status_cell("error")
        self.assertEqual(cell.text(), "✘")
        self.assertEqual(cell.foreground().color().name(), "#ff3c3c")

    def test_the_word_survives_as_the_cell_tooltip(self):
        self.assertEqual(self._status_cell("skipped").toolTip(), "skipped")


class TestRunVerdictInDetailPane(unittest.TestCase):
    """The run's own verdict is marked the same way its stages' are.

    It used to be spelled a third way again — "Success" or "Errors" in the info
    line, over a column of "completed"s, under a history list of ✔ and ✘.
    """

    def _info_text(self, status):
        record = RunRecord(
            id="2026-07-25T15-20-02", started_at="2026-07-25T15:20:02",
            finished_at="2026-07-25T15:20:02", duration_seconds=12.0,
            trigger="scheduled", status=status, stages=[],
        )
        self.widget = RunDetailWidget()
        self.widget.show_record(record)
        return self.widget._info_label.text()

    def test_a_failed_run_is_marked_with_the_red_cross(self):
        text = self._info_text("error")
        self.assertIn("✘", text)
        self.assertIn("#ff3c3c", text)

    def test_a_successful_run_is_marked_with_the_green_check(self):
        text = self._info_text("success")
        self.assertIn("✔", text)
        self.assertIn("#30a030", text)

    def test_qt_binds_the_color_to_the_mark_and_to_nothing_else(self):
        """The markup is only a promise until Qt's text engine has read it.

        The label carries a colored ``<span>``; left on AutoText, Qt decides
        rich-versus-plain by a heuristic on the string, and a wrong guess would
        show the user a literal ``<span style=…>`` and no color anywhere. So
        parse the label's text the way the label does and ask the resulting
        document what color it gave each run of characters.

        Not by rendering it: the drawn pixels also depend on the platform's font
        having a ✘ at all, which a headless runner's does not — it draws the rest
        of the line and simply omits the glyph.
        """
        document = QTextDocument()
        document.setHtml(self._info_text("error"))
        colored = {}
        block = document.firstBlock()
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            color = fragment.charFormat().foreground()
            if color.style() != Qt.BrushStyle.NoBrush:
                colored[fragment.text()] = color.color().name()
            iterator += 1
        self.assertEqual(colored, {"✘": "#ff3c3c"})


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


class TestNonAiUpscaleSummary(unittest.TestCase):
    """The non-AI row should read as prose: which video, how far, what happened.

    Its result is mostly strings, which the generic numeric dump drops entirely
    — leaving a bare "suspended=True" and no way to tell which clip was encoding
    or why an in-flight percent vanished between runs.
    """

    def _result(self, **overrides):
        result = {
            "started": "", "in_flight": "", "in_flight_percent": None,
            "suspended": False, "promoted": "", "stopped": "",
            "start_deferred": "", "failed": "", "pending": 395,
            "deferred_low_disk": False,
        }
        result.update(overrides)
        return _summarize_result(result, None, "upscale_non_ai")

    def test_names_the_video_being_encoded(self):
        summary = self._result(in_flight="larkin/1 clips/Delia Moss.mp4",
                               in_flight_percent=72)
        self.assertIn("larkin/1 clips/Delia Moss.mp4", summary)
        self.assertIn("72%", summary)

    def test_a_frozen_encode_says_it_is_paused_and_why(self):
        summary = self._result(in_flight="larkin/1 clips/Delia Moss.mp4",
                               in_flight_percent=72, suspended=True)
        self.assertIn("paused", summary)
        self.assertIn("you're at the machine", summary)
        self.assertNotIn("suspended=True", summary)

    def test_a_finished_encode_names_what_it_promoted(self):
        """Why an in-flight percent vanishes between runs: the encode landed."""
        summary = self._result(promoted="larkin/1 clips/POV Scene 3.mp4",
                               start_deferred="user_present", pending=394)
        self.assertIn("finished", summary)
        self.assertIn("larkin/1 clips/POV Scene 3.mp4", summary)

    def test_a_died_encode_names_what_failed(self):
        """The other way a percent vanishes: ffmpeg died partway through."""
        summary = self._result(failed="larkin/1 clips/Scene Five 1.mp4",
                               start_deferred="cooldown", pending=399)
        self.assertIn("failed", summary)
        self.assertIn("larkin/1 clips/Scene Five 1.mp4", summary)

    def test_a_fresh_start_names_the_video_it_kicked_off(self):
        summary = self._result(started="larkin/1 clips/Scene Three 9.mp4")
        self.assertIn("started", summary)
        self.assertIn("larkin/1 clips/Scene Three 9.mp4", summary)

    def test_an_idle_stage_says_why_nothing_is_running(self):
        summary = self._result(start_deferred="cooldown")
        self.assertIn("cooldown", summary)

    def test_always_reports_how_many_clips_are_left(self):
        self.assertIn("395 queued", self._result())
        self.assertIn("395 queued",
                      self._result(in_flight="larkin/1 clips/Delia Moss.mp4",
                                   in_flight_percent=72))

    def test_a_stopped_encode_says_the_clip_keeps_its_place(self):
        """Stopping is no fault of the video, unlike failing — it stays queued."""
        summary = self._result(stopped="larkin/1 clips/Scene Four 4.mp4")
        self.assertIn("stopped", summary)
        self.assertIn("larkin/1 clips/Scene Four 4.mp4", summary)
        self.assertIn("still queued", summary)

    def test_a_low_disk_hold_is_called_out(self):
        summary = self._result(deferred_low_disk=True, start_deferred="")
        self.assertIn("low disk", summary)


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
