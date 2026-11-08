from __future__ import annotations

import unittest
from datetime import UTC, datetime

from evolver import PipelineResult
from gui.run_record import RunRecord
from tests.temp_helpers import workspace_temp_dir
from util import run_log


# On Windows logging ends every line CRLF; kept as bytes, so each mark lands on the byte offset it names.
def _as_logging_writes_them_on_windows(*texts: str) -> bytes:
    return "".join(f"[2026-07-25 08:20:02] {t}\r\n" for t in texts).encode("utf-8")


class TestRunId(unittest.TestCase):
    def test_a_run_is_named_for_the_second_it_began(self):
        started = datetime(2026, 7, 15, 3, 20, 2, tzinfo=UTC)

        assert run_log.run_id(started) == "2026-07-15T03-20-02"

    def test_the_banner_carries_that_name(self):
        assert "2026-07-15T03-20-02" in run_log.banner("2026-07-15T03-20-02")

    def test_the_record_the_window_reads_finds_the_run_the_pipelines_banner_opened(self):
        started = datetime(2026, 7, 15, 3, 20, 2, tzinfo=UTC)
        lines = _as_logging_writes_them_on_windows(run_log.banner(run_log.run_id(started)), "Stage 8 done.")
        record = RunRecord.from_pipeline_result(PipelineResult(
            stages=[], has_errors=False, duration_seconds=1.0, started_at=started,
            log_start=0, log_end=len(lines)))

        with workspace_temp_dir() as root:
            log = root / "evolver.log"
            log.write_bytes(lines)

            assert run_log.read_run(log, record.id, record.log_start, record.log_end) is not None


class TestSize(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)

    def test_a_log_that_is_there_measures_its_bytes(self):
        log = self.root / "evolver.log"
        log.write_bytes(_as_logging_writes_them_on_windows("a line"))

        assert run_log.size(log) == len(_as_logging_writes_them_on_windows("a line"))

    def test_a_log_that_is_not_there_measures_none_rather_than_zero(self):
        assert run_log.size(self.root / "no-such.log") is None


class TestReadRun(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.log = self.root / "evolver.log"
        self.run_id = "2026-07-25T15-20-02"
        self.before = _as_logging_writes_them_on_windows(run_log.banner("2026-07-25T15-10-02"), "an earlier run")
        self.mine = _as_logging_writes_them_on_windows(run_log.banner(self.run_id),
                           "=== Stage 1: strays ===", "Stage 8 done.")
        self.after = _as_logging_writes_them_on_windows(run_log.banner("2026-07-25T15-30-02"), "a later run")
        self.log.write_bytes(self.before + self.mine + self.after)
        self.start = len(self.before)
        self.end = self.start + len(self.mine)

    def _read(self, **kwargs):
        return run_log.read_run(self.log, self.run_id, self.start, self.end,
                                **kwargs)

    def test_it_reads_the_marked_stretch_and_only_that(self):
        text = self._read()

        assert "=== Stage 1: strays ===" in text
        assert "Stage 8 done." in text
        assert "an earlier run" not in text
        assert "a later run" not in text

    def test_the_lines_come_back_one_to_a_line(self):
        assert len(self._read().splitlines()) == 3
        assert "\r" not in self._read()

    def test_a_run_with_no_mark_reads_as_nothing_to_show(self):
        assert run_log.read_run(self.log, self.run_id, None, None) is None

    def test_a_log_that_is_gone_reads_as_nothing_to_show(self):
        self.log.unlink()

        assert self._read() is None

    def test_a_log_trimmed_back_past_the_mark_reads_as_nothing_to_show(self):
        self.log.write_bytes(self.before)

        assert self._read() is None

    def test_a_run_is_read_where_its_mark_points_and_never_searched_for_through_a_log_nothing_rotates(self):
        self.log.write_bytes(self.mine + self.before)

        assert run_log.read_run(self.log, self.run_id, len(self.mine), len(self.mine) + len(self.before)) is None

    def test_a_run_that_wrote_nothing_but_its_banner_reads_back_as_that_banner_not_as_nothing_to_show(self):
        banner_alone = _as_logging_writes_them_on_windows(run_log.banner(self.run_id))
        self.log.write_bytes(self.before + banner_alone)

        text = run_log.read_run(self.log, self.run_id, len(self.before), len(self.before) + len(banner_alone))

        assert text.endswith(run_log.banner(self.run_id))

    def test_a_mark_landing_on_another_runs_lines_is_refused(self):
        self.log.write_bytes(_as_logging_writes_them_on_windows("a fresh log") * 40)

        assert self._read() is None

    def test_the_banner_opens_what_comes_back_so_the_window_says_which_run_it_shows(self):
        assert self._read().splitlines()[0].endswith(run_log.banner(self.run_id))

    def test_a_stretch_past_the_ceiling_says_so_instead_of_running_on(self):
        text = self._read(max_bytes=60)

        assert text.endswith(run_log.TRUNCATION_NOTE)
        assert len(text) < 200


if __name__ == "__main__":
    unittest.main()
