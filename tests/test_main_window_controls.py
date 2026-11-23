from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QIcon, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QToolBar,
    QToolButton,
)
from shared_ui.colors import BG_BUTTON, BORDER_SUBTLE, GREEN, RED, TOGGLE_ON
from shared_ui.icons import icon_pixmap, inline_icon
from shared_ui.spacing import BUTTON_GAP, MARGIN_STANDARD
from shared_ui.testing import questions_answered

from evolver import STAGE_LABELS, STAGE_TOOLTIPS
from gui.main_window import EvolverMainWindow, RunDetailWidget
from gui.schedule_state import ScheduleStatus
from gui.stage_details import details_of as _summarize_result
from gui.tray import EvolverTray
from tasks.scripts_sync import ScriptsSyncResult
from tests.gui_support import QAPP, build_evolver_app
from tests.temp_helpers import make_run_record, override_config


def _column_of_names(widget) -> list[str]:
    table = widget._table
    return [table.item(row, 1).text() for row in range(table.rowCount())]


def _row_of(widget, shown_as: str) -> int:
    return _column_of_names(widget).index(shown_as)


_A_ZONE_PINNED_AGAINST_THE_COMPUTERS_OWN = ZoneInfo("America/Los_Angeles")

class TestRunDetailRendering:
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
        return widget._table.item(_row_of(widget, shown_as), 4).text()

    def test_metadata_row_shows_scraped_and_errors(self):
        widget = RunDetailWidget()
        widget.show_record(self._record())
        details = self._row_details(widget, STAGE_LABELS["metadata"])
        assert details == "0 prompts read, 58 failed to read"

    def test_the_stage_column_reads_the_stage_name_not_its_key(self):
        widget = RunDetailWidget()
        widget.show_record(self._record())

        row = _row_of(widget, STAGE_LABELS["metadata"])
        assert widget._table.item(row, 1).toolTip() == STAGE_TOOLTIPS["metadata"]

    def test_each_section_heading_sits_above_its_stages_in_the_order_they_run(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(stages=[
            {"name": "metadata", "status": "completed", "duration_seconds": 1.0},
            {"name": "strays", "status": "completed", "duration_seconds": 1.0},
        ]))

        assert _column_of_names(widget) == [
            "Housekeeping", "Handle stray files", "AI videos", "Transfer prompts"]

    def test_a_heading_spans_the_row_with_no_number_status_or_time(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(stages=[
            {"name": "strays", "status": "completed", "duration_seconds": 1.0}]))

        table = widget._table
        assert table.item(0, 1).font().bold()
        assert table.columnSpan(0, 1) == table.columnCount() - 1
        assert table.item(0, 0) is None or table.item(0, 0).text() == ""
        assert not table.item(0, 1).flags() & Qt.ItemFlag.ItemIsSelectable

    def test_a_heading_stands_apart_from_its_stages_in_a_larger_font_on_a_band_of_its_own(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(stages=[
            {"name": "strays", "status": "completed", "duration_seconds": 1.0}]))

        table = widget._table
        heading, stage = table.item(0, 1), table.item(1, 1)
        assert heading.font().pointSizeF() > stage.font().pointSizeF()
        assert heading.background().style() != Qt.BrushStyle.NoBrush
        assert table.rowHeight(0) > table.rowHeight(1)

    def test_a_stage_since_taken_out_comes_last_under_no_heading(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(stages=[
            {"name": "purge", "status": "completed", "duration_seconds": 1.0},
            {"name": "strays", "status": "completed", "duration_seconds": 1.0},
        ]))

        assert _column_of_names(widget) == ["Housekeeping", "Handle stray files", "Purge Trash"]

    def test_a_stage_since_taken_out_shows_the_name_it_last_had(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(
            stages=[{"name": "references", "status": "completed", "duration_seconds": 1.0},
                    {"name": "purge", "status": "completed", "duration_seconds": 1.0}],
        ))

        assert [widget._table.item(row, 1).text() for row in (0, 1)] == [
            "Follow moved videos", "Purge Trash"]

    def test_a_stage_since_taken_out_has_no_number_in_the_stage_column(self):
        widget = RunDetailWidget()
        widget.show_record(make_run_record(
            stages=[{"name": "references", "status": "completed", "duration_seconds": 1.0}],
        ))

        assert widget._table.item(0, 0).text() == "—"


class TestRunHistoryMarks:
    def _item(self, status):
        record = make_run_record(status=status)
        self.window = EvolverMainWindow()
        with patch("gui.main_window.newest_runs", return_value=[record]):
            self.window.refresh_history()
        return self.window._history_list.item(0)

    def test_a_failed_run_leaves_its_timestamp_the_default_color(self):
        item = self._item("error")
        assert item.foreground().style() == Qt.BrushStyle.NoBrush, (
            "a whole red row could not be told from a run one of whose stages failed")

    def test_a_failed_run_carries_the_cross_as_its_icon(self):
        assert not self._item("error").icon().isNull()

    def test_the_label_itself_is_just_the_time_and_duration(self):
        with override_config(DISPLAY_TIMEZONE=_A_ZONE_PINNED_AGAINST_THE_COMPUTERS_OWN):
            assert self._item("success").text() == "2026/07/25 08:20 (12s)"

    def test_refreshing_selects_the_newest_run_and_shows_its_detail(self):
        self.window = EvolverMainWindow()
        newest = make_run_record(id="2026-07-25T15-20-02", duration_seconds=34.0)
        older = make_run_record(id="2026-07-25T15-10-02", duration_seconds=99.0)
        with patch("gui.main_window.newest_runs", return_value=[newest, older]):
            self.window.refresh_history()
        assert self.window._history_list.currentRow() == 0
        shown = _words_of(self.window._detail_widget._run_line)
        assert "34" in shown
        assert "99" not in shown

    def test_a_run_that_ends_joins_the_list_without_the_history_being_read_again(self):
        self.window = EvolverMainWindow()
        older = [make_run_record(id=f"2026-07-25T15-{minute:02d}-02") for minute in (10, 0)]
        with patch("gui.main_window.newest_runs", return_value=older):
            self.window.refresh_history()
        newest = make_run_record(id="2026-07-25T15-20-02", duration_seconds=34.0)

        self.window._runs_shown = 2
        with patch("gui.main_window.newest_runs", side_effect=AssertionError("read the history again")):
            self.window.add_run(newest)

        assert self.window._records == [newest, older[0]]
        assert self.window._history_list.count() == 2
        assert self.window._history_list.currentRow() == 0
        assert "34" in _words_of(self.window._detail_widget._run_line)

    def test_closing_the_window_hides_it_to_the_tray_instead(self):
        self.window = EvolverMainWindow()
        self.window.show()
        assert self.window.isVisible()
        closed = self.window.close()
        assert closed is False
        assert not self.window.isVisible()


def _words_of(label: QLabel) -> str:
    document = QTextDocument()
    document.setHtml(label.text())
    return document.toPlainText()


def _drawn(icon: QIcon):
    return icon.pixmap(16).toImage()


class TestStageStatusColumn:
    def _status_cell(self, status):
        record = make_run_record(
            status="error",
            stages=[{"name": "upscale_non_ai", "status": status,
                     "duration_seconds": 1.0, "result": None}],
        )
        # Held on self: Qt deletes the table's C++ items with a widget collected as a local.
        self.widget = RunDetailWidget()
        self.widget.show_record(record)
        return self.widget._table.item(_row_of(self.widget, STAGE_LABELS["upscale_non_ai"]), 2)

    def test_a_completed_stage_shows_a_green_check(self):
        cell = self._status_cell("completed")
        assert _drawn(cell.icon()) == _drawn(QIcon(icon_pixmap("check", 16, GREEN)))

    def test_an_errored_stage_shows_a_red_cross(self):
        cell = self._status_cell("error")
        assert _drawn(cell.icon()) == _drawn(QIcon(icon_pixmap("cross", 16, RED)))

    def test_a_cell_that_is_its_mark_alone_wears_it_in_the_middle(self):
        cell = self._status_cell("completed")
        table = self.widget._table
        table.resize(600, 200)
        table.setColumnWidth(2, 80)
        rect = table.visualItemRect(cell)
        image = table.viewport().grab(rect).toImage()
        inked = [x for y in range(image.height()) for x in range(image.width())
                 if image.pixelColor(x, y).green() > 120 and image.pixelColor(x, y).red() < 100]
        assert inked
        assert abs((min(inked) + max(inked)) / 2 - image.width() / 2) <= 2

    def test_the_word_survives_as_the_cell_tooltip(self):
        assert self._status_cell("skipped").toolTip() == "skipped"


class TestRunVerdictInDetailPane:
    def _info_text(self, status):
        record = make_run_record(status=status)
        self.widget = RunDetailWidget()
        self.widget.show_record(record)
        return self.widget._run_line.text()

    def test_a_failed_run_is_marked_with_the_red_cross(self):
        text = self._info_text("error")
        assert inline_icon("cross", color=RED, size=self._mark_side()) in text

    def test_a_successful_run_is_marked_with_the_green_check(self):
        text = self._info_text("success")
        assert inline_icon("check", color=GREEN, size=self._mark_side()) in text

    def _mark_side(self) -> int:
        return self.widget._run_line.fontMetrics().height()

    def test_qt_binds_the_color_to_the_mark_and_to_nothing_else(self):
        document = QTextDocument()
        document.setHtml(self._info_text("error"))
        images, colored = 0, []
        block = document.firstBlock()
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.charFormat().isImageFormat():
                images += 1
            elif (fragment.charFormat().foreground().style() != Qt.BrushStyle.NoBrush
                  and not fragment.charFormat().isAnchor()):
                colored.append(fragment.text())
            iterator += 1
        assert (images, colored) == (1, [])


class TestScriptsSyncSummary:
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

    def test_differing_version_groups_are_named_as_trouble(self):
        summary = self._result(ambiguous_variant_groups=2)

        assert summary == "2 version groups whose scripts differ — none copied"

    def test_differing_version_groups_leave_the_stage_ok(self):
        assert ScriptsSyncResult(ambiguous_variant_groups=2).ok, (
            "whether they fail the stage is the stage's call, not the window's")

    def test_names_the_scripts_that_matched_no_video(self):
        summary = self._result(
            unmatched=2,
            unmatched_paths=["2D/non_AI/studio/scene one.funscript",
                             "2D/non_AI/studio/scene two.funscript"],
        )
        assert "scene one.funscript" in summary
        assert "scene two.funscript" in summary

    def test_names_each_kind_of_trouble_beside_the_scripts_it_caught(self):
        summary = self._result(
            unmatched=1, unmatched_paths=["alpha/scene one.funscript"],
            ambiguous=1, ambiguous_paths=["beta/scene two.funscript"],
            collisions=1, collision_paths=["gamma/scene three.funscript"],
            variant_copy_errors=1, variant_copy_error_paths=["delta/scene four.funscript"],
        )
        assert summary == (
            "1 match no video (alpha/scene one.funscript); "
            "1 match more than one video (beta/scene two.funscript); "
            "1 cannot move — a different script holds the destination (gamma/scene three.funscript); "
            "1 failed to copy to a version (delta/scene four.funscript)"
        )

    def test_stands_in_a_count_for_the_names_it_cannot_fit(self):
        summary = self._result(unmatched=5, unmatched_paths=[f"clip {i}.funscript" for i in range(5)])
        assert "clip 0.funscript" in summary
        assert "+2 more" in summary
        assert "clip 4.funscript" not in summary

    def test_a_late_counter_still_reaches_a_failing_row(self):
        summary = self._result(moved=3, already_aligned=53, collisions=1, copied_variants=2,
                               ambiguous_variant_groups=1, variant_copy_errors=1)
        assert "1 failed to copy to a version" in summary
        assert "1 cannot move" in summary

    def test_a_clean_run_reads_as_the_work_it_did(self):
        summary = self._result(already_aligned=53, followed_to_archive=14,
                               discarded_duplicates=1)
        assert "14 followed a retired video out of the library" in summary
        assert "53 already aligned" in summary

    def test_says_how_many_funscripts_followed_a_video_renamed_by_hand(self):
        assert "2 followed a video renamed by hand" in self._result(followed_renames=2)

    def test_an_old_record_without_the_paths_still_summarizes(self):
        summary = _summarize_result({"already_aligned": 53, "unmatched": 15}, None, "scripts")
        assert "15 match no video" in summary

    def test_says_how_many_were_not_checked_and_which_folder_could_not_be_reached(self):
        summary = self._result(already_aligned=350, not_checked=15, unreachable=["Q:/cloud/VR"])
        assert summary == "15 not checked: Q:/cloud/VR cannot be reached; 350 already aligned"

    def test_a_run_that_checked_nothing_says_why(self):
        summary = self._result(not_checked=15, unreachable=["Q:/cloud/VR"])
        assert summary == "15 not checked: Q:/cloud/VR cannot be reached"

    def test_what_went_unchecked_follows_what_went_wrong(self):
        summary = self._result(ambiguous=1, ambiguous_paths=["beta/scene two.funscript"],
                               not_checked=15, unreachable=["Q:/cloud/VR"])
        assert summary == ("1 match more than one video (beta/scene two.funscript); "
                           "15 not checked: Q:/cloud/VR cannot be reached")


class TestNonAiUpscaleSummary:
    def _result(self, **overrides):
        result = {
            "started": "", "in_flight": "", "in_flight_percent": None,
            "suspended": False, "promoted": "", "stopped": "",
            "start_deferred": "", "failed": "", "pending": 395,
            "percent_complete": None, "remaining_seconds": 0.0,
            "unmeasured_videos": 0, "deferred_low_disk": False,
            "on_request": False,
        }
        result.update(overrides)
        return _summarize_result(result, None, "upscale_non_ai")

    def test_names_the_video_being_encoded(self):
        summary = self._result(in_flight="lagoon/1 clips/Delia Moss.mp4",
                               in_flight_percent=72)
        assert "lagoon/1 clips/Delia Moss.mp4" in summary
        assert "72%" in summary

    def test_a_frozen_encode_says_it_is_paused_and_why(self):
        summary = self._result(in_flight="lagoon/1 clips/Delia Moss.mp4",
                               in_flight_percent=72, suspended=True)
        assert "paused" in summary
        assert "you're at the computer" in summary
        assert "suspended=True" not in summary

    def test_a_finished_encode_names_what_it_promoted(self):
        summary = self._result(promoted="lagoon/1 clips/Scene Three 3.mp4",
                               start_deferred="user_present", pending=394)
        assert "finished" in summary
        assert "lagoon/1 clips/Scene Three 3.mp4" in summary

    def test_a_finished_encode_waiting_for_the_archive_says_what_it_waits_for(self):
        summary = self._result(in_flight="lagoon/1 clips/scene one.mp4", unreachable_archive="Q:/archive")
        assert summary.startswith(
            "finished lagoon/1 clips/scene one.mp4, waiting until Q:/archive can be reached "
            "to take the original, ")

    def test_a_died_encode_names_what_failed(self):
        summary = self._result(failed="lagoon/1 clips/Scene Five 1.mp4",
                               start_deferred="cooldown", pending=399)
        assert "failed" in summary
        assert "lagoon/1 clips/Scene Five 1.mp4" in summary

    def test_a_fresh_start_names_the_video_it_kicked_off(self):
        summary = self._result(started="lagoon/1 clips/Scene Three 9.mp4")
        assert "started" in summary
        assert "lagoon/1 clips/Scene Three 9.mp4" in summary

    def test_an_encode_you_asked_for_says_so_beside_its_progress(self):
        summary = self._result(in_flight="lagoon/1 clips/Delia Moss.mp4",
                               in_flight_percent=12, on_request=True)
        assert "encoding lagoon/1 clips/Delia Moss.mp4 (12%, at your request)" in summary, (
            "the one encode running while you are at the computer would look like a failed presence check")

    def test_a_start_you_asked_for_says_so(self):
        summary = self._result(started="lagoon/1 clips/Scene Three 9.mp4", on_request=True)
        assert "started lagoon/1 clips/Scene Three 9.mp4 at your request" in summary

    def test_an_idle_stage_says_why_nothing_is_running(self):
        summary = self._result(start_deferred="cooldown")
        assert "cooldown" in summary

    def test_always_reports_how_many_clips_are_left(self):
        assert "395 queued" in self._result()
        assert "395 queued" in self._result(
            in_flight="lagoon/1 clips/Delia Moss.mp4", in_flight_percent=72,
        )

    def test_says_how_far_along_by_running_time(self):
        summary = self._result(pending=180, percent_complete=29,
                               remaining_seconds=149_400.0)
        assert "180 queued" in summary
        assert "29% done" in summary, "the short videos went first, so a count runs ahead of the work"
        assert "41.5h left" in summary

    def test_a_library_nothing_has_measured_yet_still_says_the_count(self):
        summary = self._result(pending=180, percent_complete=None)
        assert summary == "nothing to do (180 queued)"

    def test_a_part_measured_library_says_how_much_it_cannot_see(self):
        summary = self._result(pending=180, percent_complete=29,
                               remaining_seconds=149_400.0, unmeasured_videos=12)
        assert "12 not yet measured" in summary

    def test_a_stopped_encode_says_the_clip_keeps_its_place(self):
        summary = self._result(stopped="lagoon/1 clips/Scene Four 4.mp4")
        assert "stopped" in summary
        assert "lagoon/1 clips/Scene Four 4.mp4" in summary
        assert "still queued" in summary

    def test_two_outcomes_of_one_run_read_as_a_list(self):
        summary = self._result(promoted="lagoon/1 clips/scene one.mp4", start_deferred="topaz_busy")

        assert summary.startswith("finished lagoon/1 clips/scene one.mp4, waiting (topaz_busy), ")

    def test_a_run_that_started_nothing_says_so_first_and_how_far_along_in_parentheses(self):
        summary = self._result(pending=84, percent_complete=44, remaining_seconds=117_000.0)

        assert summary == "nothing to do (84 queued, 32.5h left, 44% done)"

    def test_a_low_disk_hold_is_called_out(self):
        summary = self._result(deferred_low_disk=True, start_deferred="")
        assert "the disk is nearly full" in summary

    def test_an_encode_that_has_not_reported_yet_reads_progress_unknown(self):
        summary = self._result(in_flight="lagoon/1 clips/Delia Moss.mp4")
        assert "progress unknown" in summary


@pytest.fixture
def window():
    return EvolverMainWindow()


def _menu_entries(tray):
    return ["---" if action.isSeparator() else action.text()
            for action in tray.contextMenu().actions()]


def _toolbar_entries(window):
    entries = []
    for group in window._button_groups:
        if entries:
            entries.append("---")
        entries += [button.text() for button in group]
    return entries


class TestToolbarMatchesTheTrayMenu:

    @pytest.mark.parametrize("status", [ScheduleStatus(), ScheduleStatus(is_paused=True)],
                             ids=["scheduling", "paused"])
    def test_it_offers_the_menus_commands_in_the_menus_words_groups_and_order(
            self, window, status):
        tray = EvolverTray()
        tray.show_schedule(status)
        window.show_schedule(status)
        menu = _menu_entries(tray)
        bar = _toolbar_entries(window)

        assert bar[bar.index("Run now"):] == menu[menu.index("Run now"):]


def _shown(window):
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    QAPP.processEvents()
    return window._button_row


def _button_for(row, action):
    [button] = [widget for widget in row.findChildren(QToolButton) if widget.defaultAction() is action]
    return button


def _top_left(widget, window) -> QPoint:
    return widget.mapTo(window, QPoint(0, 0))


def _columns_wearing(image, color) -> list[int]:
    return [x for x in range(image.width()) for y in range(image.height())
            if image.pixelColor(x, y).name() == color.name()]


def _as_painted(window, action):
    window.show()
    QAPP.processEvents()
    button = _button_for(window._button_row, action)
    painted = QAPP.primaryScreen().grabWindow(window.winId()).toImage()
    return button, painted.copy(QRect(button.mapTo(window, QPoint(0, 0)), button.size()))


class TestUpscaleNonAiOnTheToolbar:

    def test_its_switch_is_painted_on_its_own_button(self, window):
        window.set_nonai_enabled(True)
        _button, painted = _as_painted(window, window.nonai_action)
        assert len(_columns_wearing(painted, TOGGLE_ON)) > 30

    def test_its_switch_sits_clear_of_its_name(self, window):
        window.set_nonai_enabled(True)
        button, drawn = _as_painted(window, window.nonai_action)
        words = button.palette().color(QPalette.ColorRole.ButtonText)

        name_ends = (min(_columns_wearing(drawn, words))
                     + button.fontMetrics().horizontalAdvance(button.text()))
        assert name_ends < min(_columns_wearing(drawn, TOGGLE_ON))

    def test_clicking_its_name_throws_its_switch(self, window):
        window.nonai_action.trigger()
        assert window.nonai_switch.isChecked()


class TestToolbarButtonsLookLikeButtons:

    def test_a_button_at_rest_wears_the_familys_border_round_its_ground(self, window):
        _button, drawn = _as_painted(window, window.settings_action)
        middle = drawn.height() // 2
        assert drawn.pixelColor(0, middle).name() == BORDER_SUBTLE.name()
        assert drawn.pixelColor(3, middle).name() == BG_BUTTON.name()


class TestToolbarSpacing:

    def test_pause_scheduling_has_no_more_room_around_its_words_than_run_now(self, window):
        toolbar = _shown(window)

        def room_around_the_words(action):
            button = _button_for(toolbar, action)
            return button.width() - button.fontMetrics().horizontalAdvance(button.text())

        assert (room_around_the_words(window.pause_action)
                == room_around_the_words(window.run_now_action))

    def test_quit_stands_the_familys_margin_in_from_the_windows_right_edge(self, window):
        toolbar = _shown(window)
        quit_button = _button_for(toolbar, window.quit_action)

        assert window.width() - (quit_button.mapTo(window, QPoint(0, 0)).x() + quit_button.width()) == MARGIN_STANDARD

    def test_the_buttons_stand_the_familys_margin_below_the_windows_top_edge(self, window):
        toolbar = _shown(window)

        assert _button_for(toolbar, window.run_now_action).mapTo(window, QPoint(0, 0)).y() == MARGIN_STANDARD


class TestTheNextRunSitsBesideRunHistory:

    def _shown_with(self, window, status):
        window.show_schedule(status)
        _shown(window)
        [heading] = [label for label in window.findChildren(QLabel) if label.text() == "Run history"]
        return heading

    def test_it_reads_in_parentheses(self, window):
        window.show_schedule(ScheduleStatus(next_run_at=datetime(2026, 3, 29, 14, 30, tzinfo=UTC)))

        assert window._next_run_label.text() == "(Next run: 14:30)"

    def test_it_is_on_the_run_history_line_just_after_it(self, window):
        heading = self._shown_with(window, ScheduleStatus(is_running=True))
        here, there = heading.geometry(), window._next_run_label.geometry()

        assert window._next_run_label.parent() is heading.parent()
        assert there.center().y() == here.center().y()
        assert 0 < there.left() - here.right() <= heading.fontMetrics().horizontalAdvance("  ")

    def test_run_history_sits_on_the_buttons_row_so_it_takes_no_line_of_its_own(self, window):
        heading = self._shown_with(window, ScheduleStatus(is_running=True))
        run_now = _button_for(window._button_row, window.run_now_action)

        assert (_top_left(heading, window).y() + heading.height() // 2
                == _top_left(run_now, window).y() + run_now.height() // 2)
        assert _top_left(window._history_list, window).y() > _top_left(run_now, window).y() + run_now.height()

    def test_run_history_starts_where_the_list_under_it_starts(self, window):
        heading = self._shown_with(window, ScheduleStatus(is_running=True))

        assert (heading.mapTo(window, QPoint(0, 0)).x()
                == window._history_list.mapTo(window, QPoint(0, 0)).x())


def _rows_of(window) -> dict[int, list[QToolButton]]:
    rows: dict[int, list[QToolButton]] = {}
    for group in window._button_groups:
        for button in group:
            rows.setdefault(_top_left(button, window).y(), []).append(button)
    return rows


class TestTheWholeToolbarShows:

    @pytest.mark.parametrize("status", [
        ScheduleStatus(next_run_at=datetime(2026, 10, 8, 19, 30, tzinfo=UTC)),
        ScheduleStatus(is_running=True),
        ScheduleStatus(is_paused=True),
    ], ids=["scheduled", "running", "paused"])
    def test_on_one_row_as_the_window_opens_whatever_the_next_run_line_says(self, window, status):
        window.show_schedule(status)
        _shown(window)

        assert len(_rows_of(window)) == 1

    def test_no_button_hides_behind_a_more_button(self, window):
        assert window.findChildren(QToolBar) == []


class TestANarrowWindowWrapsItsButtons:

    def _narrow(self, window):
        _shown(window)
        widest_group = max(sum(button.width() for button in group) + BUTTON_GAP * (len(group) - 1)
                           for group in window._button_groups)
        window.resize(max(window.minimumWidth(), widest_group + 2 * MARGIN_STANDARD + 10), window.height())
        QAPP.processEvents()
        return _rows_of(window)

    def test_buttons_that_do_not_fit_move_down_to_a_second_row(self, window):
        assert len(self._narrow(window)) >= 2

    def test_no_group_is_split_across_two_rows(self, window):
        self._narrow(window)

        for group in window._button_groups:
            assert len({_top_left(button, window).y() for button in group}) == 1, [b.text() for b in group]

    def test_every_row_lines_up_with_the_right_edge(self, window):
        rows = self._narrow(window)

        right_edges = {max(_top_left(button, window).x() + button.width() for button in row)
                       for row in rows.values()}
        assert right_edges == {window.width() - MARGIN_STANDARD}

    def test_run_history_stays_on_the_first_row(self, window):
        rows = self._narrow(window)
        [heading] = [label for label in window.findChildren(QLabel) if label.text() == "Run history"]

        assert _top_left(heading, window).y() <= min(rows)


class TestMainWindowToolbarExists:

    def test_restart_action_has_icon(self, window):
        assert not window.restart_action.icon().isNull()

    def test_the_pause_button_starts_as_pause_scheduling(self, window):
        assert window.pause_action.text() == "Pause scheduling"


class TestToolbarStateUpdates:
    def test_next_run_shown_when_scheduled(self, window):
        next_run = datetime(2026, 3, 29, 14, 30, tzinfo=UTC)
        window.show_schedule(ScheduleStatus(next_run_at=next_run))
        assert "14:30" in window._next_run_label.text()

    def test_paused_reads_paused_as_the_tray_says_it(self, window):
        window.show_schedule(ScheduleStatus(is_paused=True))
        assert window._next_run_label.text() == "(Paused)"

    def test_running_message_when_running(self, window):
        window.show_schedule(ScheduleStatus(is_running=True))
        assert "Running" in window._next_run_label.text()

    def test_run_now_disabled_when_running(self, window):
        window.show_schedule(ScheduleStatus(is_running=True))
        assert not window.run_now_action.isEnabled()

    def test_run_now_enabled_when_idle(self, window):
        next_run = datetime(2026, 3, 29, 15, 0, tzinfo=UTC)
        window.show_schedule(ScheduleStatus(next_run_at=next_run))
        assert window.run_now_action.isEnabled()

    def test_a_run_in_flight_outranks_a_pause_here_as_in_the_tray(self, window):
        window.show_schedule(ScheduleStatus(is_running=True, is_paused=True))
        assert window._next_run_label.text() == "(Running...)"

    def test_the_pause_button_reads_resume_scheduling_while_paused(self, window):
        window.show_schedule(ScheduleStatus(is_paused=True))
        assert window.pause_action.iconText() == "Resume scheduling"

    def test_the_pause_button_reads_pause_scheduling_once_resumed(self, window):
        window.show_schedule(ScheduleStatus(is_paused=True))
        window.show_schedule(ScheduleStatus(next_run_at=datetime.now(UTC)))
        assert window.pause_action.iconText() == "Pause scheduling"


class TestEachToolbarButtonDoesItsJob:
    @pytest.fixture
    def app(self, request):
        return build_evolver_app(request)

    def test_the_quit_button_asks_first_and_a_yes_quits(self, app, monkeypatch):
        asked = questions_answered(monkeypatch, QMessageBox.StandardButton.Yes)
        with patch.object(app._app, "quit") as mock_quit:
            app._window.quit_action.trigger()
        assert len(asked) == 1, (
            "fired and checked by what it does: a count of receivers passed with Quit wired to the wrong slot")
        mock_quit.assert_called_once()

    def test_the_quit_question_has_yes_as_the_default(self, app, monkeypatch):
        asked = questions_answered(monkeypatch, QMessageBox.StandardButton.No)
        with patch.object(app._app, "quit"):
            app._window.quit_action.trigger()
        [box] = asked
        assert box.title == "Quit Evolver"
        assert box.default == QMessageBox.StandardButton.Yes

    def test_a_no_to_the_quit_confirmation_changes_nothing(self, app, monkeypatch):
        questions_answered(monkeypatch, QMessageBox.StandardButton.No)
        with patch.object(app._app, "quit") as mock_quit:
            app._window.quit_action.trigger()
        mock_quit.assert_not_called()

    def test_run_now_starts_a_manual_pipeline_run(self, app):
        with patch("gui.run_controller.PipelineWorker") as mock_worker:
            app._window.run_now_action.trigger()
        assert mock_worker.call_args.kwargs["trigger"] == "manual"
        mock_worker.return_value.start.assert_called_once()

    def test_the_trays_run_now_starts_a_manual_run_too(self, app):
        with patch("gui.run_controller.PipelineWorker") as mock_worker:
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
        app._background = MagicMock()
        with patch("gui.app.StatsWindow") as mock_stats:
            app._window.stats_action.trigger()
        mock_stats.assert_called_once_with(app._window)
        mock_stats.return_value.show.assert_called_once()

    def test_the_trays_stats_item_opens_the_stats_window_too(self, app):
        app._background = MagicMock()
        with patch("gui.app.StatsWindow") as mock_stats:
            app._tray.stats_action.trigger()
        mock_stats.return_value.show.assert_called_once()

    def test_the_pause_button_pauses_and_resumes_the_scheduler(self, app):
        assert not app._scheduler.is_paused
        app._window.pause_action.trigger()
        assert app._scheduler.is_paused
        app._window.pause_action.trigger()
        assert not app._scheduler.is_paused

    def test_the_trays_pause_item_toggles_the_scheduler_too(self, app):
        app._tray.pause_action.trigger()
        assert app._scheduler.is_paused
        app._tray.pause_action.trigger()
        assert not app._scheduler.is_paused

    def test_the_restart_button_relaunches_the_app_and_quits_this_one(self, app):
        with patch("gui.app.production_update.start_again_after") as start_again, \
             patch.object(app, "_shutdown") as mock_quit:
            app._window.restart_action.trigger()
        start_again.assert_called_once()
        mock_quit.assert_called_once()

    def test_the_trays_restart_item_relaunches_too(self, app):
        with patch("gui.app.production_update.start_again_after") as start_again, \
             patch.object(app, "_shutdown") as mock_quit:
            app._tray.restart_action.trigger()
        start_again.assert_called_once()
        mock_quit.assert_called_once()

    def test_the_trays_open_item_shows_the_window(self, app):
        assert not app._window.isVisible()
        app._tray.open_action.trigger()
        assert app._window.isVisible()

    def test_the_trays_quit_item_quits_without_asking(self, app, monkeypatch):
        # The tray binds the bound _quit, so only QApplication.quit is observable.
        asked = questions_answered(monkeypatch, QMessageBox.StandardButton.No)
        with patch.object(app._app, "quit") as mock_app_quit:
            app._tray.quit_action.trigger()
        mock_app_quit.assert_called_once()
        assert asked == []
