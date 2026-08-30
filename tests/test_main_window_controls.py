"""Tests for the main window toolbar controls (quit, settings, toggle, next run, run now)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QMessageBox, QToolBar

from gui.main_window import EvolverMainWindow, RunDetailWidget, _summarize_result
from tasks.stages import STAGE_LABELS, STAGE_TOOLTIPS
from gui.toggle_switch import ToggleSwitch
from tests.gui_support import build_evolver_app
from tests.temp_helpers import make_run_record


class TestRunDetailRendering:
    """RunDetailWidget should surface scrape successes alongside errors."""

    def _record(self):
        return make_run_record(
            id="2026-06-27T22-18-46", started_at="2026-06-27T22:18:46",
            finished_at="2026-06-27T22:18:46", duration_seconds=699.7,
            trigger="manual", status="error",
            stages=[
                {"name": "metadata", "status": "completed", "duration_seconds": 477.0,
                 "result": {"newly_scraped": 0, "already_scraped": 0,
                            "skipped_failed": 0, "no_scrape_strat": 0, "errors": 58}},
            ],
        )

    def _row_details(self, widget, shown_as):
        for row in range(widget._table.rowCount()):
            if widget._table.item(row, 1).text() == shown_as:
                return widget._table.item(row, 4).text()
        return None

    def test_metadata_row_shows_scraped_and_errors(self):
        widget = RunDetailWidget()
        widget.show_record(self._record())
        details = self._row_details(widget, STAGE_LABELS["metadata"])
        assert "newly_scraped=0" in details
        assert "errors=58" in details

    def test_the_stage_column_reads_the_stage_name_not_its_key(self):
        """The table is what you read after a run; the key is what the record
        files it under, and the two are not the same word."""
        widget = RunDetailWidget()
        widget.show_record(self._record())

        assert widget._table.item(0, 1).text() == STAGE_LABELS["metadata"]
        assert widget._table.item(0, 1).toolTip() == STAGE_TOOLTIPS["metadata"]

    def test_a_stage_the_registry_does_not_list_still_shows_its_key(self):
        """Records on disk go back months and name stages this build has since
        retired, so a row must render rather than raise or come out blank."""
        widget = RunDetailWidget()
        widget.show_record(make_run_record(
            id="x", started_at="2026-06-27T22:18:46", finished_at="2026-06-27T22:18:46",
            duration_seconds=1.0, trigger="manual", status="success",
            stages=[{"name": "regen_cutover", "status": "completed", "duration_seconds": 1.0}],
        ))

        assert widget._table.item(0, 1).text() == "regen_cutover"
        assert widget._table.item(0, 0).text() == "\u2014"


class TestRunHistoryMarks:
    """A run's verdict is its mark's color, never the whole line's."""

    def _item(self, status):
        record = make_run_record(status=status)
        self.window = EvolverMainWindow()
        with patch("gui.main_window.load_runs", return_value=[record]):
            self.window.refresh_history()
        return self.window._history_list.item(0)

    def test_a_failed_run_leaves_its_timestamp_the_default_color(self):
        """Reddening the timestamp too made the line shout without saying why."""
        item = self._item("error")
        assert item.foreground().style() == Qt.BrushStyle.NoBrush

    def test_a_failed_run_carries_the_cross_as_its_icon(self):
        assert not self._item("error").icon().isNull()

    def test_the_label_itself_is_just_the_time_and_duration(self):
        assert self._item("success").text() == "2026/07/25 08:20 (12s)"

    def test_refreshing_selects_the_newest_run_and_shows_its_detail(self):
        """This selection is what populates the detail pane when the window
        opens; without it the right half of the window is simply empty."""
        self.window = EvolverMainWindow()
        newest = make_run_record(id="2026-07-25T15-20-02", duration_seconds=34.0)
        older = make_run_record(id="2026-07-25T15-10-02", duration_seconds=99.0)
        with patch("gui.main_window.load_runs", return_value=[newest, older]):
            self.window.refresh_history()
        assert self.window._history_list.currentRow() == 0
        info = self.window._detail_widget._info_label.text()
        assert "34" in info
        assert "99" not in info

    def test_closing_the_window_hides_it_to_the_tray_instead(self):
        """The X must not quit the app: the tray icon keeps it alive, and the
        ignored close event is the whole difference."""
        self.window = EvolverMainWindow()
        self.window.show()
        assert self.window.isVisible()
        closed = self.window.close()
        assert closed is False  # the close event was ignored
        assert not self.window.isVisible()  # ...and the window hid itself


class TestStageStatusColumn:
    """The Status column is a symbol, and only the symbol carries the color."""

    def _status_cell(self, status):
        record = make_run_record(
            status="error",
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
        assert cell.text() == "✔"
        assert cell.foreground().color().name() == "#30a030"

    def test_an_errored_stage_shows_a_red_cross(self):
        """The row a low-disk hold now produces, which no run record had before."""
        cell = self._status_cell("error")
        assert cell.text() == "✘"
        assert cell.foreground().color().name() == "#ff3c3c"

    def test_the_word_survives_as_the_cell_tooltip(self):
        assert self._status_cell("skipped").toolTip() == "skipped"


class TestRunVerdictInDetailPane:
    """The run's own verdict is marked the same way its stages' are.

    It used to be spelled a third way again — "Success" or "Errors" in the info
    line, over a column of "completed"s, under a history list of ✔ and ✘.
    """

    def _info_text(self, status):
        record = make_run_record(status=status)
        self.widget = RunDetailWidget()
        self.widget.show_record(record)
        return self.widget._info_label.text()

    def test_a_failed_run_is_marked_with_the_red_cross(self):
        text = self._info_text("error")
        assert "✘" in text
        assert "#ff3c3c" in text

    def test_a_successful_run_is_marked_with_the_green_check(self):
        text = self._info_text("success")
        assert "✔" in text
        assert "#30a030" in text

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
        assert colored == {"✘": "#ff3c3c"}


class TestSummarizeResult:
    """Stage detail summaries should make scrape success-vs-error legible."""

    def test_metadata_shows_scraped_and_errors_even_when_zero(self):
        result = {"newly_scraped": 0, "no_scrape_strat": 0,
                  "skipped_unknown_orient": 0, "errors": 58}
        summary = _summarize_result(result, None, "metadata")
        assert "newly_scraped=0" in summary
        assert "errors=58" in summary

    def test_other_stages_still_hide_zero_fields(self):
        result = {"moved": 103, "deleted_collisions": 0, "skipped_unknown": 0}
        summary = _summarize_result(result, None, "sort")
        assert "moved=103" in summary
        assert "deleted_collisions" not in summary

    def test_skip_reason_takes_precedence(self):
        summary = _summarize_result(None, "upscale_pending", "verify")
        assert summary == "Reason: upscale_pending"


class TestScriptsSyncSummary:
    """A red scripts row should say what is wrong and which scripts are at fault.

    The generic numeric dump renders the failure as one bland tally among
    several ("already_aligned=53, unmatched=15"), with nothing marking which is
    the problem — and it keeps only the first five counters, so a late one can
    be dropped from a failing row entirely.
    """

    def _result(self, **overrides):
        result = {
            "moved": 0, "already_aligned": 0, "unmatched": 0, "ambiguous": 0,
            "collisions": 0, "copied_variants": 0, "ambiguous_variant_groups": 0,
            "variant_copy_errors": 0, "followed_to_archive": 0,
            "discarded_duplicates": 0, "unmatched_paths": [],
        }
        result.update(overrides)
        return _summarize_result(result, None, "scripts")

    def test_says_what_is_wrong_in_words(self):
        summary = self._result(already_aligned=53, unmatched=15)
        assert "15 match no video" in summary
        assert "unmatched=15" not in summary

    def test_names_the_scripts_that_matched_no_video(self):
        summary = self._result(
            unmatched=2,
            unmatched_paths=["2D/non_AI/studio/scene one.funscript",
                             "2D/non_AI/studio/scene two.funscript"],
        )
        assert "scene one.funscript" in summary
        assert "scene two.funscript" in summary

    def test_stands_in_a_count_for_the_names_it_cannot_fit(self):
        summary = self._result(unmatched=5, unmatched_paths=[f"clip {i}.funscript" for i in range(5)])
        assert "clip 0.funscript" in summary
        assert "+2 more" in summary
        assert "clip 4.funscript" not in summary

    def test_a_late_counter_still_reaches_a_failing_row(self):
        """Six non-zero counters: the five-field truncation dropped the last."""
        summary = self._result(moved=3, already_aligned=53, collisions=1, copied_variants=2,
                               ambiguous_variant_groups=1, variant_copy_errors=1)
        assert "1 failed to copy to a variant" in summary
        assert "1 cannot move" in summary

    def test_a_clean_run_reads_as_the_work_it_did(self):
        summary = self._result(already_aligned=53, followed_to_archive=14,
                               discarded_duplicates=1)
        assert "14 followed a retired video out of the library" in summary
        assert "53 already aligned" in summary

    def test_an_old_record_without_the_paths_still_summarizes(self):
        summary = _summarize_result({"already_aligned": 53, "unmatched": 15}, None, "scripts")
        assert "15 match no video" in summary


class TestNonAiUpscaleSummary:
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
        assert "larkin/1 clips/Delia Moss.mp4" in summary
        assert "72%" in summary

    def test_a_frozen_encode_says_it_is_paused_and_why(self):
        summary = self._result(in_flight="larkin/1 clips/Delia Moss.mp4",
                               in_flight_percent=72, suspended=True)
        assert "paused" in summary
        assert "you're at the machine" in summary
        assert "suspended=True" not in summary

    def test_a_finished_encode_names_what_it_promoted(self):
        """Why an in-flight percent vanishes between runs: the encode landed."""
        summary = self._result(promoted="larkin/1 clips/Scene Three 3.mp4",
                               start_deferred="user_present", pending=394)
        assert "finished" in summary
        assert "larkin/1 clips/Scene Three 3.mp4" in summary

    def test_a_died_encode_names_what_failed(self):
        """The other way a percent vanishes: ffmpeg died partway through."""
        summary = self._result(failed="larkin/1 clips/Scene Five 1.mp4",
                               start_deferred="cooldown", pending=399)
        assert "failed" in summary
        assert "larkin/1 clips/Scene Five 1.mp4" in summary

    def test_a_fresh_start_names_the_video_it_kicked_off(self):
        summary = self._result(started="larkin/1 clips/Scene Three 9.mp4")
        assert "started" in summary
        assert "larkin/1 clips/Scene Three 9.mp4" in summary

    def test_an_idle_stage_says_why_nothing_is_running(self):
        summary = self._result(start_deferred="cooldown")
        assert "cooldown" in summary

    def test_always_reports_how_many_clips_are_left(self):
        assert "395 queued" in self._result()
        assert "395 queued" in self._result(
            in_flight="larkin/1 clips/Delia Moss.mp4", in_flight_percent=72,
        )

    def test_a_stopped_encode_says_the_clip_keeps_its_place(self):
        """Stopping is no fault of the video, unlike failing — it stays queued."""
        summary = self._result(stopped="larkin/1 clips/Scene Four 4.mp4")
        assert "stopped" in summary
        assert "larkin/1 clips/Scene Four 4.mp4" in summary
        assert "still queued" in summary

    def test_a_low_disk_hold_is_called_out(self):
        summary = self._result(deferred_low_disk=True, start_deferred="")
        assert "low disk" in summary

    def test_an_encode_that_has_not_reported_yet_reads_progress_unknown(self):
        """A non-AI encode reports no percent until ffmpeg's first progress
        line; the row must say so rather than render a blank or a crash."""
        summary = self._result(in_flight="larkin/1 clips/Delia Moss.mp4")
        assert "progress unknown" in summary


@pytest.fixture
def window():
    return EvolverMainWindow()


class TestMainWindowToolbarExists:
    """The main window should have a toolbar with all tray-equivalent controls."""

    def test_has_toolbar(self, window):
        toolbars = window.findChildren(QToolBar)
        assert len(toolbars) >= 1

    def test_has_restart_action(self, window):
        assert window.restart_action is not None

    def test_restart_action_has_icon(self, window):
        assert not window.restart_action.icon().isNull()

    def test_has_quit_action(self, window):
        assert window.quit_action is not None

    def test_has_settings_action(self, window):
        assert window.settings_action is not None

    def test_has_run_now_action(self, window):
        assert window.run_now_action is not None

    def test_has_active_toggle(self, window):
        assert window.active_toggle is not None

    def test_active_toggle_is_toggle_switch(self, window):
        assert isinstance(window.active_toggle, ToggleSwitch)

    def test_active_toggle_starts_checked(self, window):
        assert window.active_toggle.isChecked()


class TestToolbarStateUpdates:
    """update_schedule_status should keep toolbar widgets in sync."""

    def test_next_run_shown_when_scheduled(self, window):
        next_run = datetime(2026, 3, 29, 14, 30)
        window.update_schedule_status(False, False, next_run)
        assert "14:30" in window._next_run_label.text()

    def test_inactive_message_when_paused(self, window):
        window.update_schedule_status(False, True, None)
        assert "inactive" in window._next_run_label.text().lower()

    def test_running_message_when_running(self, window):
        window.update_schedule_status(True, False, None)
        assert "Running" in window._next_run_label.text()

    def test_run_now_disabled_when_running(self, window):
        window.update_schedule_status(True, False, None)
        assert not window.run_now_action.isEnabled()

    def test_run_now_enabled_when_idle(self, window):
        next_run = datetime(2026, 3, 29, 15, 0)
        window.update_schedule_status(False, False, next_run)
        assert window.run_now_action.isEnabled()

    def test_toggle_unchecked_when_paused(self, window):
        window.update_schedule_status(False, True, None)
        assert not window.active_toggle.isChecked()

    def test_toggle_checked_when_active(self, window):
        window.update_schedule_status(False, True, None)
        window.update_schedule_status(False, False, datetime.now())
        assert window.active_toggle.isChecked()


class TestToggleSwitch:
    """The pause control: what a click does, and what the user sees.

    mousePressEvent and paintEvent were both entirely uncovered -- 'clicking
    Active pauses the pipeline' had no test at any level while three tests
    exercised the two trivial accessors.
    """

    def test_starts_unchecked_and_set_checked_round_trips(self):
        toggle = ToggleSwitch()
        assert not toggle.isChecked()
        toggle.setChecked(True)
        assert toggle.isChecked()
        toggle.setChecked(False)
        assert not toggle.isChecked()

    def test_a_click_flips_the_state_and_announces_the_new_value(self):
        from PyQt6.QtTest import QTest

        toggle = ToggleSwitch()
        announced = []
        toggle.clicked.connect(announced.append)
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        assert toggle.isChecked()
        assert announced == [True]
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        assert not toggle.isChecked()
        assert announced == [True, False]

    def test_the_switch_states_its_size_once(self):
        """`setFixedSize` pins minimum and maximum, so the layout takes 44x22
        from it and a `sizeHint` override could not change any outcome. One of
        the two, never both — a second statement of the size can only disagree
        with the first."""
        from PyQt6.QtWidgets import QHBoxLayout, QWidget

        host = QWidget()
        QHBoxLayout(host).addWidget(ToggleSwitch())
        host.resize(400, 200)
        host.layout().activate()

        toggle = host.layout().itemAt(0).widget()
        assert (toggle.width(), toggle.height()) == (44, 22)
        assert "sizeHint" not in ToggleSwitch.__dict__

    def test_the_knob_and_track_show_which_state_it_is_in(self):
        """The paint is the only thing that tells the user the pipeline runs:
        on is a blue track with the knob right, off a gray track, knob left."""
        from PyQt6.QtGui import QImage

        def rendered(toggle):
            image = QImage(44, 22, QImage.Format.Format_ARGB32)
            image.fill(0xFFFF00FF)
            toggle.render(image)
            return image

        off = rendered(ToggleSwitch())
        assert off.pixelColor(11, 11).getRgb()[:3] == (255, 255, 255)  # knob left
        assert off.pixelColor(33, 11).getRgb()[:3] == (176, 176, 176)  # gray track

        on = rendered(ToggleSwitch(checked=True))
        assert on.pixelColor(11, 11).getRgb()[:3] == (48, 128, 224)  # blue track
        assert on.pixelColor(33, 11).getRgb()[:3] == (255, 255, 255)  # knob right


class TestToolbarAppWiring:
    """Triggering each control produces that control's effect.

    These used to assert ``action.receivers(action.triggered) > 0``, which is
    true for a connection to anything at all — rewiring Quit, Run Now and
    Settings all to _show_window left the whole suite green (audit probe P8).
    Every test here fires the real action and asserts what the user gets, with
    the collaborator patched at the gui.app boundary.
    """

    @pytest.fixture
    def app(self, request):
        return build_evolver_app(request)

    def _quit_confirmation(self, answer):
        box = patch("gui.app.QMessageBox")
        mock_box = box.start()
        mock_box.StandardButton.Yes = QMessageBox.StandardButton.Yes
        mock_box.StandardButton.No = QMessageBox.StandardButton.No
        mock_box.question.return_value = answer
        return box, mock_box

    def test_the_quit_button_asks_first_and_a_yes_quits(self, app):
        box, mock_box = self._quit_confirmation(QMessageBox.StandardButton.Yes)
        try:
            with patch.object(app, "_quit") as mock_quit:
                app._window.quit_action.trigger()
        finally:
            box.stop()
        mock_box.question.assert_called_once()
        mock_quit.assert_called_once()

    def test_a_no_to_the_quit_confirmation_changes_nothing(self, app):
        box, _ = self._quit_confirmation(QMessageBox.StandardButton.No)
        try:
            with patch.object(app, "_quit") as mock_quit:
                app._window.quit_action.trigger()
        finally:
            box.stop()
        mock_quit.assert_not_called()

    def test_run_now_starts_a_manual_pipeline_run(self, app):
        with patch("gui.app.PipelineWorker") as mock_worker:
            app._window.run_now_action.trigger()
        assert mock_worker.call_args.kwargs["trigger"] == "manual"
        mock_worker.return_value.start.assert_called_once()

    def test_the_trays_run_now_starts_a_manual_run_too(self, app):
        with patch("gui.app.PipelineWorker") as mock_worker:
            app._tray.run_now_action.trigger()
        assert mock_worker.call_args.kwargs["trigger"] == "manual"
        mock_worker.return_value.start.assert_called_once()

    def test_the_settings_button_opens_the_settings_dialog(self, app):
        with patch("gui.app.SettingsDialog") as mock_dialog:
            mock_dialog.return_value.exec.return_value = False
            app._window.settings_action.trigger()
        mock_dialog.assert_called_once_with(app._settings, app._window)
        mock_dialog.return_value.exec.assert_called_once()

    def test_the_trays_settings_item_opens_the_same_dialog(self, app):
        with patch("gui.app.SettingsDialog") as mock_dialog:
            mock_dialog.return_value.exec.return_value = False
            app._tray.settings_action.trigger()
        mock_dialog.assert_called_once_with(app._settings, app._window)

    def test_the_stats_button_opens_the_stats_window(self, app):
        with patch("gui.app.StatsWindow") as mock_stats, \
             patch("gui.app.load_runs", return_value=[]) as mock_load:
            app._window.stats_action.trigger()
        mock_stats.assert_called_once_with([], app._window)
        mock_stats.return_value.show.assert_called_once()
        mock_load.assert_called_once()

    def test_the_trays_stats_item_opens_the_stats_window_too(self, app):
        with patch("gui.app.StatsWindow") as mock_stats, \
             patch("gui.app.load_runs", return_value=[]):
            app._tray.stats_action.trigger()
        mock_stats.return_value.show.assert_called_once()

    def test_the_active_toggle_pauses_and_resumes_the_scheduler(self, app):
        assert not app._scheduler.is_paused
        app._window.active_toggle.clicked.emit(False)
        assert app._scheduler.is_paused
        app._window.active_toggle.clicked.emit(True)
        assert not app._scheduler.is_paused

    def test_the_trays_pause_item_toggles_the_scheduler_too(self, app):
        app._tray.pause_action.trigger()
        assert app._scheduler.is_paused
        app._tray.pause_action.trigger()
        assert not app._scheduler.is_paused

    def test_the_restart_button_relaunches_the_app_and_quits_this_one(self, app):
        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit") as mock_quit:
            app._window.restart_action.trigger()
        argv = mock_popen.call_args.args[0]
        assert any("tray_app.py" in str(part) for part in argv)
        mock_quit.assert_called_once()

    def test_the_trays_restart_item_relaunches_too(self, app):
        with patch("gui.app.subprocess.Popen") as mock_popen, \
             patch.object(app, "_quit") as mock_quit:
            app._tray.restart_action.trigger()
        argv = mock_popen.call_args.args[0]
        assert any("tray_app.py" in str(part) for part in argv)
        mock_quit.assert_called_once()

    def test_the_trays_open_item_shows_the_window(self, app):
        assert not app._window.isVisible()
        app._tray.open_action.trigger()
        assert app._window.isVisible()

    def test_the_trays_quit_item_quits_without_asking(self, app):
        # The tray connects straight to the bound _quit, so patching the
        # attribute cannot intercept it; the observable end of _quit is the
        # QApplication being asked to exit.
        with patch.object(app._app, "quit") as mock_app_quit, \
             patch("gui.app.QMessageBox") as mock_box:
            app._tray.quit_action.trigger()
        mock_app_quit.assert_called_once()
        mock_box.question.assert_not_called()
