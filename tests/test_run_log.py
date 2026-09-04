"""Reading back the bytes a run marked as its own.

The mark is two byte offsets and a banner. The offsets make the read a seek
rather than a search of a file nothing rotates; the banner is what keeps a
stale offset from showing somebody else's run under this run's title.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tests.temp_helpers import workspace_temp_dir
from util import run_log


def _lines(*texts: str) -> bytes:
    """Log lines as the file really holds them: stamped, CRLF, UTF-8.

    Bytes, not text, because the mark is a byte offset: a fixture written in
    whichever newline the platform prefers puts every offset out by a byte a
    line, and the test would then pass or fail by where it ran.
    """
    return "".join(f"[2026-07-25 08:20:02] {t}\r\n" for t in texts).encode("utf-8")


class TestRunId(unittest.TestCase):
    def test_a_run_is_named_for_the_second_it_began(self):
        started = datetime(2026, 7, 15, 3, 20, 2, tzinfo=UTC)

        self.assertEqual(run_log.run_id(started), "2026-07-15T03-20-02")

    def test_the_banner_carries_that_name(self):
        """It is how a byte offset is checked, so the name has to be in it."""
        self.assertIn("2026-07-15T03-20-02",
                      run_log.banner("2026-07-15T03-20-02"))


class TestSize(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)

    def test_a_log_that_is_there_measures_its_bytes(self):
        log = self.root / "evolver.log"
        log.write_bytes(_lines("a line"))

        self.assertEqual(run_log.size(log), len(_lines("a line")))

    def test_a_log_that_is_not_there_measures_none_rather_than_zero(self):
        """Zero is a real offset -- the top of a log that exists -- so a run
        that could not be marked has to answer differently from one that
        starts at the beginning."""
        self.assertIsNone(run_log.size(self.root / "no-such.log"))


class TestReadRun(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.log = self.root / "evolver.log"
        self.run_id = "2026-07-25T15-20-02"
        self.before = _lines(run_log.banner("2026-07-25T15-10-02"), "an earlier run")
        self.mine = _lines(run_log.banner(self.run_id),
                           "=== Stage 1: strays ===", "Stage 8 done.")
        self.after = _lines(run_log.banner("2026-07-25T15-30-02"), "a later run")
        self.log.write_bytes(self.before + self.mine + self.after)
        self.start = len(self.before)
        self.end = self.start + len(self.mine)

    def _read(self, **kwargs):
        return run_log.read_run(self.log, self.run_id, self.start, self.end,
                                **kwargs)

    def test_it_reads_the_marked_stretch_and_only_that(self):
        text = self._read()

        self.assertIn("=== Stage 1: strays ===", text)
        self.assertIn("Stage 8 done.", text)
        self.assertNotIn("an earlier run", text)
        self.assertNotIn("a later run", text)

    def test_the_lines_come_back_one_to_a_line(self):
        """logging writes this file in text mode, so every line ends CRLF; a
        text widget handed those draws a blank line between every one."""
        self.assertEqual(len(self._read().splitlines()), 3)
        self.assertNotIn("\r", self._read())

    def test_a_run_with_no_mark_reads_as_nothing_to_show(self):
        self.assertIsNone(
            run_log.read_run(self.log, self.run_id, None, None))

    def test_a_log_that_is_gone_reads_as_nothing_to_show(self):
        self.log.unlink()

        self.assertIsNone(self._read())

    def test_a_log_trimmed_back_past_the_mark_reads_as_nothing_to_show(self):
        self.log.write_bytes(self.before)

        self.assertIsNone(self._read())

    def test_a_mark_landing_on_another_runs_lines_is_refused(self):
        """The case the banner exists for. A log deleted and started again is
        the same file to an offset, and the offsets still land inside it -- so
        without the check this shows a stranger's run under this run's title."""
        self.log.write_bytes(_lines("a fresh log") * 40)

        self.assertIsNone(self._read())

    def test_the_banner_opens_what_comes_back(self):
        """It is the first thing a run writes, so it is the first line read --
        and it names the run, which is what makes the window self-identifying
        rather than an anonymous slab of log."""
        self.assertTrue(
            self._read().splitlines()[0].endswith(run_log.banner(self.run_id)))

    def test_a_stretch_past_the_ceiling_says_so_instead_of_running_on(self):
        text = self._read(max_bytes=60)

        self.assertTrue(text.endswith(run_log.TRUNCATION_NOTE))
        self.assertLess(len(text), 200)


if __name__ == "__main__":
    unittest.main()
