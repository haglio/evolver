from __future__ import annotations

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument

import gui.main_window
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow, RunDetailWidget
from tests.gui_support import build_evolver_app
from tests.product_sources import gui_modules_imported_by
from tests.temp_helpers import make_run_record, override_config, workspace_temp_dir
from util import run_log


def _log_bytes(lines) -> bytes:
    body = "".join(f"[2026-07-25 {at}] {text}\r\n" for at, text in lines)
    return body.encode("utf-8")


class TestTheRunsTitleLinksToTheLogTheOnlyPlaceWhatTheStagesSaidIsKept(unittest.TestCase):
    def setUp(self):
        self.widget = RunDetailWidget()
        self.addCleanup(self.widget.deleteLater)

    def _links(self) -> list[str]:
        document = QTextDocument()
        document.setHtml(self.widget._header.text())
        found = []
        iterator = document.firstBlock().begin()
        while not iterator.atEnd():
            href = iterator.fragment().charFormat().anchorHref()
            if href:
                found.append(href)
            iterator += 1
        return found

    def test_a_shown_run_puts_a_link_on_its_title(self):
        self.widget.show_record(make_run_record())

        assert self._links() == ["log"]

    def test_the_link_is_one_the_mouse_can_reach(self):
        self.widget.show_record(make_run_record())

        flags = self.widget._header.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.LinksAccessibleByMouse

    def test_the_title_still_reads_as_the_run_it_names(self):
        self.widget.show_record(make_run_record(started_at="2026-07-25T15:20:02"))

        document = QTextDocument()
        document.setHtml(self.widget._header.text())
        assert document.toPlainText() == "Run: 2026-07-25T15:20:02"

    def test_clicking_it_asks_for_that_run_and_no_other(self):
        record = make_run_record(id="2026-07-25T15-20-02")
        asked = []
        self.widget.log_requested.connect(asked.append)
        self.widget.show_record(record)

        self.widget._on_title_clicked("log")

        assert asked == [record]

    def test_with_no_run_shown_the_title_is_not_a_link(self):
        self.widget.show_record(make_run_record())
        self.widget.clear()

        assert self._links() == []

    def test_a_click_with_no_run_shown_asks_for_nothing(self):
        asked = []
        self.widget.log_requested.connect(asked.append)

        self.widget._on_title_clicked("log")

        assert asked == []

    def test_the_title_link_wears_the_palettes_link_color_having_none_of_its_own(self):
        self.widget.show_record(make_run_record())

        assert "color" not in self.widget._header.text().lower()

    def test_the_window_passes_the_request_on_to_the_app_which_owns_every_window_beside_it(self):
        window = EvolverMainWindow()
        self.addCleanup(window.deleteLater)
        asked = []
        window.log_requested.connect(asked.append)
        record = make_run_record()

        window._detail_widget.show_record(record)
        window._detail_widget._on_title_clicked("log")

        assert asked == [record]
        assert gui_modules_imported_by(gui.main_window) & {"gui.log_window", "gui.stats_window"} == set()


class TestLogWindowOpens(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.log = self.root / "evolver.log"
        self.app = build_evolver_app(self)
        self.addCleanup(self._close_log_window)

    def _close_log_window(self):
        if self.app._log_window is not None:
            self.app._log_window.close()
            self.app._log_window.deleteLater()

    def _marked_record(self, run_id="2026-07-25T15-20-02"):
        before = _log_bytes([("08:10:02", run_log.banner("2026-07-25T15-10-02"))])
        mine = _log_bytes([
            ("08:20:02", run_log.banner(run_id)),
            ("08:20:02", "=== Stage 1: strays ==="),
            ("08:20:05", "Stage 8 done."),
        ])
        after = _log_bytes([("08:30:02", run_log.banner("2026-07-25T15-30-02"))])
        self.log.write_bytes(before + mine + after)
        return make_run_record(id=run_id, log_start=len(before),
                               log_end=len(before) + len(mine))

    def _shown(self):
        return self.app._log_window._view.toPlainText()

    def test_the_window_holds_this_runs_lines_and_not_the_whole_log_which_nothing_rotates(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        assert "=== Stage 1: strays ===" in self._shown()
        assert "Stage 8 done." in self._shown()
        assert "2026-07-25T15-10-02" not in self._shown()
        assert "2026-07-25T15-30-02" not in self._shown()

    def test_the_title_says_which_run_is_on_screen(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        assert "(12s)" in self.app._log_window.windowTitle()

    def test_a_second_click_replaces_the_window_rather_than_stacking_one(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)
            first = self.app._log_window
            self.app._show_run_log(record)

        assert self.app._log_window is not first

    def test_a_run_from_before_the_mark_says_that_is_why(self):
        self._marked_record()
        record = make_run_record(log_start=None, log_end=None)

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        assert self._shown() == ""
        assert "predates" in self.app._log_window._view.placeholderText()

    def test_a_mark_the_log_no_longer_answers_to_says_that_instead(self):
        record = self._marked_record()
        self.log.write_bytes(_log_bytes([("08:20:02", "a fresh log")] * 40))

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        assert self._shown() == ""
        assert "no longer holds" in self.app._log_window._view.placeholderText()

    def test_it_reads_the_configured_log_and_not_a_path_of_its_own(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log), \
                patch("gui.app.run_log.read_run", return_value="") as read:
            self.app._show_run_log(record)

        assert read.call_args.args[0] == self.log


class TestLogWindowWidget(unittest.TestCase):
    def test_lines_carrying_full_paths_scroll_rather_than_wrap_so_the_timestamps_stay_in_one_column(self):
        window = RunLogWindow("2026/07/25 08:20 (12s)", "a line")
        self.addCleanup(window.deleteLater)

        assert window._view.lineWrapMode() == window._view.LineWrapMode.NoWrap
        assert window._view.isReadOnly()


if __name__ == "__main__":
    unittest.main()
