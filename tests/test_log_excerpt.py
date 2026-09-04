"""Finding one run's stretch of a log nothing rotates.

The real log is hundreds of megabytes of months of runs, so the search has to
be a bisect over the file's bytes rather than a read of it. Every fixture here
is built from an aware UTC moment converted the way the module converts, so
these pass in whatever timezone the machine runs in.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tests.temp_helpers import workspace_temp_dir
from util import log_excerpt

_BASE = datetime(2026, 4, 12, 18, 30, 0, tzinfo=timezone.utc)


def _line(moment: datetime, message: str) -> str:
    """One log line, stamped the way logging stamps them: local, to the second."""
    local = moment.astimezone().replace(tzinfo=None)
    return f"[{local.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"


class TestExcerpt(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.log = self.root / "evolver.log"

    def _write(self, lines):
        self.log.write_text("".join(lines), encoding="utf-8")

    def _at(self, seconds: float) -> datetime:
        return _BASE + timedelta(seconds=seconds)

    def test_only_the_lines_inside_the_run_come_back(self):
        self._write([
            _line(self._at(-600), "the run before"),
            _line(self._at(0), "=== Stage 1: strays ==="),
            _line(self._at(3), "Stage 1 done."),
            _line(self._at(600), "the run after"),
        ])

        text = log_excerpt.excerpt(self.log, self._at(0), self._at(3))

        self.assertEqual(
            text.splitlines(),
            [_line(self._at(0), "=== Stage 1: strays ===").rstrip("\n"),
             _line(self._at(3), "Stage 1 done.").rstrip("\n")],
        )

    def test_a_line_a_second_before_the_recorded_start_is_still_the_run(self):
        """A stamp is the second a line was written IN, truncated, so the first
        line of a run reads as a fraction before the run's own start. Compared
        directly it falls outside, and what is lost is the line naming the
        stage that opened the run."""
        self._write([
            _line(self._at(-1), "=== Stage 1: strays ==="),
            _line(self._at(2), "Stage 1 done."),
        ])

        text = log_excerpt.excerpt(self.log, self._at(0), self._at(2))

        self.assertIn("=== Stage 1: strays ===", text)

    def test_a_traceback_rides_along_with_the_record_it_trails(self):
        """logging writes an exception as ONE record: the continuation lines
        carry no stamp of their own, and dropping them would leave the excerpt
        saying a stage failed and not saying how."""
        self._write([
            _line(self._at(-600), "the run before"),
            "Traceback (most recent call last):\n",
            "  the run before's traceback\n",
            _line(self._at(1), "Stage 2 failed"),
            "Traceback (most recent call last):\n",
            "  RuntimeError: invented failure\n",
            _line(self._at(600), "the run after"),
        ])

        text = log_excerpt.excerpt(self.log, self._at(0), self._at(1))

        self.assertIn("RuntimeError: invented failure", text)
        self.assertNotIn("the run before's traceback", text)

    def test_a_span_the_log_does_not_reach_back_to_comes_back_empty(self):
        self._write([_line(self._at(600), "the only run this log has")])

        self.assertEqual(
            log_excerpt.excerpt(self.log, self._at(-600), self._at(-590)), "")

    def test_a_log_that_is_not_there_comes_back_empty(self):
        self.assertEqual(
            log_excerpt.excerpt(self.root / "no-such.log",
                                self._at(0), self._at(3)), "")

    def test_the_run_is_found_in_a_log_of_many_blocks(self):
        """The bisect is the whole point: the real log is far past one block,
        and a linear read of it would be the thing this module exists to
        avoid. Padding either side puts the run in the middle of several."""
        pad = 4000  # ~60 bytes a line, so the run sits several blocks in
        lines = [_line(self._at(-3600), f"earlier run line {i}") for i in range(pad)]
        lines.append(_line(self._at(0), "=== Stage 1: strays ==="))
        lines.append(_line(self._at(4), "Stage 1 done."))
        lines += [_line(self._at(3600), f"later run line {i}") for i in range(pad)]
        self._write(lines)
        self.assertGreater(self.log.stat().st_size, 4 << 16)

        text = log_excerpt.excerpt(self.log, self._at(0), self._at(4))

        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("=== Stage 1: strays ===", text)

    def test_the_read_starts_within_a_block_of_the_run_it_is_after(self):
        """What makes the excerpt cheap rather than merely correct.

        The test above would pass just as well on a read of the whole file, so
        the bisect's own answer is asserted here: the offset it hands the
        linear read is the block before the run, not the top of the file.
        """
        pad = 4000
        lines = [_line(self._at(-3600), f"earlier run line {i}") for i in range(pad)]
        lines.append(_line(self._at(0), "=== Stage 1: strays ==="))
        self._write(lines)
        size = self.log.stat().st_size
        target = self._at(0).astimezone().replace(tzinfo=None)

        with self.log.open("rb") as handle:
            offset = log_excerpt._block_before(handle, size, target)

        run_at = len("".join(lines[:pad]))
        self.assertLessEqual(offset, run_at)
        self.assertGreater(offset, run_at - 2 * (1 << 16))

    def test_an_excerpt_past_the_ceiling_says_so_instead_of_running_on(self):
        self._write([_line(self._at(0), f"line {i}") for i in range(500)])

        text = log_excerpt.excerpt(self.log, self._at(0), self._at(1),
                                   max_bytes=200)

        self.assertTrue(text.endswith(log_excerpt.TRUNCATION_NOTE))
        self.assertLess(len(text), 1000)


if __name__ == "__main__":
    unittest.main()
