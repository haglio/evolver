"""The run title is the way into the log, and the window it opens.

A run record holds each stage's counters. What the stages actually said --
which file, which error, which decision -- was only ever written to the log,
and the log is one appending file nothing rotates, so finding a run's few dozen
lines by hand means scrolling months of them. The title carries the link that
lands on them.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument

from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow, RunDetailWidget
from tests.gui_support import build_evolver_app
from tests.temp_helpers import make_run_record, override_config, workspace_temp_dir
from util import run_log


def _log_bytes(lines) -> bytes:
    """Log lines as the file really holds them: stamped, CRLF, UTF-8."""
    body = "".join(f"[2026-07-25 {at}] {text}\r\n" for at, text in lines)
    return body.encode("utf-8")


class TestRunTitleIsALink(unittest.TestCase):
    def setUp(self):
        self.widget = RunDetailWidget()
        self.addCleanup(self.widget.deleteLater)

    def _links(self) -> list[str]:
        """The title's link targets, read the way the label reads them."""
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

        self.assertEqual(self._links(), ["log"])

    def test_the_link_is_one_the_mouse_can_reach(self):
        """The markup alone is not a link. A QLabel emits linkActivated only
        while its interaction flags allow the mouse at one, and a flag set
        elsewhere on this label -- selectable text, say -- would replace the
        default that does, leaving a title that looks like a link and does
        nothing when clicked."""
        self.widget.show_record(make_run_record())

        flags = self.widget._header.textInteractionFlags()
        self.assertTrue(flags & Qt.TextInteractionFlag.LinksAccessibleByMouse)

    def test_the_title_still_reads_as_the_run_it_names(self):
        """The link is what the title does, not what it says."""
        self.widget.show_record(make_run_record(started_at="2026-07-25T15:20:02"))

        document = QTextDocument()
        document.setHtml(self.widget._header.text())
        self.assertEqual(document.toPlainText(), "Run: 2026-07-25T15:20:02")

    def test_clicking_it_asks_for_that_run_and_no_other(self):
        record = make_run_record(id="2026-07-25T15-20-02")
        asked = []
        self.widget.log_requested.connect(asked.append)
        self.widget.show_record(record)

        self.widget._on_title_clicked("log")

        self.assertEqual(asked, [record])

    def test_with_no_run_shown_the_title_is_not_a_link(self):
        """The pane starts here, and a link to a run there is none of would
        open a window onto nothing."""
        self.widget.show_record(make_run_record())
        self.widget.clear()

        self.assertEqual(self._links(), [])

    def test_a_click_with_no_run_shown_asks_for_nothing(self):
        asked = []
        self.widget.log_requested.connect(asked.append)

        self.widget._on_title_clicked("log")

        self.assertEqual(asked, [])

    def test_the_window_passes_the_request_on(self):
        """The app owns the windows opened beside the main one, so the ask has
        to reach it rather than stopping in the pane that raised it."""
        window = EvolverMainWindow()
        self.addCleanup(window.deleteLater)
        asked = []
        window.log_requested.connect(asked.append)
        record = make_run_record()

        window._detail_widget.show_record(record)
        window._detail_widget._on_title_clicked("log")

        self.assertEqual(asked, [record])


class TestLogWindowOpens(unittest.TestCase):
    """What the app does with the ask: read the bytes the run's mark names."""

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
        """A log with this run's lines between two other runs', and its mark.

        Written as bytes, CRLF, because that is what ``logging`` writes on this
        platform and the mark is a byte offset: a fixture in whichever newline
        the test file happens to use puts every offset out by a byte a line.
        """
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

    def test_the_window_holds_this_runs_lines_and_not_its_neighbors(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertIn("=== Stage 1: strays ===", self._shown())
        self.assertIn("Stage 8 done.", self._shown())
        self.assertNotIn("2026-07-25T15-10-02", self._shown())
        self.assertNotIn("2026-07-25T15-30-02", self._shown())

    def test_the_title_says_which_run_is_on_screen(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertIn("(12s)", self.app._log_window.windowTitle())

    def test_a_second_click_replaces_the_window_rather_than_stacking_one(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)
            first = self.app._log_window
            self.app._show_run_log(record)

        self.assertIsNot(self.app._log_window, first)

    def test_a_run_from_before_the_mark_says_that_is_why(self):
        """Every record written before runs marked themselves has no mark, and
        the history keeps them for months. Saying so beats an empty window."""
        self._marked_record()
        record = make_run_record(log_start=None, log_end=None)

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertEqual(self._shown(), "")
        self.assertIn("predates", self.app._log_window._view.placeholderText())

    def test_a_mark_the_log_no_longer_answers_to_says_that_instead(self):
        """The offsets are only as good as the file under them. A log deleted
        and started again leaves marks pointing into a stranger's lines, and
        the banner is what catches it -- so the window says the log lost them
        rather than showing somebody else's run under this run's title."""
        record = self._marked_record()
        self.log.write_bytes(_log_bytes([("08:20:02", "a fresh log")] * 40))

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertEqual(self._shown(), "")
        self.assertIn("no longer holds", self.app._log_window._view.placeholderText())

    def test_it_reads_the_configured_log_and_not_a_path_of_its_own(self):
        record = self._marked_record()

        with override_config(LOG_FILE=self.log), \
                patch("gui.app.run_log.read_run", return_value="") as read:
            self.app._show_run_log(record)

        self.assertEqual(read.call_args.args[0], self.log)


class TestLogWindowWidget(unittest.TestCase):
    def test_long_lines_scroll_rather_than_wrap(self):
        """A log line carries a full path. Wrapped, one stage's line becomes
        three and the column of timestamps stops lining up."""
        window = RunLogWindow("2026/07/25 08:20 (12s)", "a line")
        self.addCleanup(window.deleteLater)

        self.assertEqual(window._view.lineWrapMode(),
                         window._view.LineWrapMode.NoWrap)
        self.assertTrue(window._view.isReadOnly())


if __name__ == "__main__":
    unittest.main()
