"""The run title is the way into the log, and the window it opens.

A run record holds each stage's counters. What the stages actually said --
which file, which error, which decision -- was only ever written to the log,
and the log is one appending file nothing rotates, so finding a run's few dozen
lines by hand means scrolling months of them. The title carries the link that
lands on them.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument

import config
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow, RunDetailWidget
from tests.gui_support import build_evolver_app
from tests.temp_helpers import make_run_record, override_config, workspace_temp_dir


def _line(moment: datetime, message: str) -> str:
    """One log line, stamped the way logging stamps them: local, to the second."""
    local = moment.astimezone().replace(tzinfo=None)
    return f"[{local.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"


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
    """What the app does with the ask: cut the run's stretch out of the log."""

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

    def _record_and_log(self, duration_seconds=4.0):
        """A run, and a log holding its lines between two other runs' lines."""
        finished = datetime.now(timezone.utc).replace(microsecond=0)
        started = finished - timedelta(seconds=duration_seconds)

        self.log.write_text("".join([
            _line(started - timedelta(seconds=600), "an earlier run"),
            _line(started, "=== Stage 1: strays ==="),
            _line(finished, "Stage 8 done."),
            _line(finished + timedelta(seconds=600), "a later run"),
        ]), encoding="utf-8")
        return make_run_record(
            started_at=started.strftime("%Y-%m-%dT%H:%M:%S"),
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%S"),
            duration_seconds=duration_seconds,
        )

    def test_the_window_holds_this_runs_lines_and_not_its_neighbors(self):
        record = self._record_and_log()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        shown = self.app._log_window._view.toPlainText()
        self.assertIn("=== Stage 1: strays ===", shown)
        self.assertIn("Stage 8 done.", shown)
        self.assertNotIn("an earlier run", shown)
        self.assertNotIn("a later run", shown)

    def test_the_title_says_which_run_is_on_screen(self):
        record = self._record_and_log()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertIn("(4s)", self.app._log_window.windowTitle())

    def test_a_second_click_replaces_the_window_rather_than_stacking_one(self):
        record = self._record_and_log()

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)
            first = self.app._log_window
            self.app._show_run_log(record)

        self.assertIsNot(self.app._log_window, first)

    def test_a_run_the_log_has_nothing_for_opens_and_says_where_it_looked(self):
        """The history outlives the log -- it is a directory of files nothing
        prunes, and the log can be deleted under it. An empty window that names
        the file it read beats one that just looks broken."""
        record = self._record_and_log()

        with override_config(LOG_FILE=self.root / "no-such.log"):
            self.app._show_run_log(record)

        self.assertEqual(self.app._log_window._view.toPlainText(), "")
        self.assertIn("no-such.log", self.app._log_window._view.placeholderText())

    def test_a_record_that_stamped_both_ends_with_the_finish_still_lands(self):
        """Every record on disk predates the fix that derives started_at, and
        says the run began the moment it ended. Read literally, a long run's
        excerpt would be the two seconds after it finished and none of it."""
        finished = datetime.now(timezone.utc).replace(microsecond=0)

        self.log.write_text("".join([
            _line(finished - timedelta(seconds=300), "=== Stage 1: strays ==="),
            _line(finished, "Stage 8 done."),
        ]), encoding="utf-8")
        stamped = finished.strftime("%Y-%m-%dT%H:%M:%S")
        record = make_run_record(started_at=stamped, finished_at=stamped,
                                 duration_seconds=300.0)

        with override_config(LOG_FILE=self.log):
            self.app._show_run_log(record)

        self.assertIn("=== Stage 1: strays ===",
                      self.app._log_window._view.toPlainText())

    def test_it_reads_the_configured_log_and_not_a_path_of_its_own(self):
        record = self._record_and_log()

        with override_config(LOG_FILE=self.log), \
                patch("gui.app.log_excerpt.excerpt", return_value="") as excerpt:
            self.app._show_run_log(record)

        self.assertEqual(excerpt.call_args.args[0], self.log)


class TestLogWindowWidget(unittest.TestCase):
    def test_long_lines_scroll_rather_than_wrap(self):
        """A log line carries a full path. Wrapped, one stage's line becomes
        three and the column of timestamps stops lining up."""
        window = RunLogWindow("2026/07/25 08:20 (12s)", "a line", config.LOG_FILE)
        self.addCleanup(window.deleteLater)

        self.assertEqual(window._view.lineWrapMode(),
                         window._view.LineWrapMode.NoWrap)
        self.assertTrue(window._view.isReadOnly())


if __name__ == "__main__":
    unittest.main()
