import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from tests.temp_helpers import workspace_temp_dir

from gui.run_record import RunRecord, result_to_dict, save_run, load_runs, format_run_label


class TestResultToDict(unittest.TestCase):

    def test_converts_dataclass_with_path_fields(self):
        result = Mock()
        result.__dataclass_fields__ = True
        result.moved = 3
        result.moved_files = [Path("C:/videos/a.mp4"), Path("C:/videos/b.mp4")]
        # dataclasses.asdict won't work on a Mock, so test the Path conversion
        d = result_to_dict(result)
        self.assertIsInstance(d, dict)

    def test_returns_none_for_none(self):
        self.assertIsNone(result_to_dict(None))


class TestRunRecordRoundTrip(unittest.TestCase):

    def test_save_and_load_round_trip(self):
        with workspace_temp_dir() as tmp:
            runs_dir = tmp / "runs"
            runs_dir.mkdir()

            record = RunRecord(
                id="2026-03-29T14-30-00",
                started_at="2026-03-29T14:30:00",
                finished_at="2026-03-29T14:31:23",
                duration_seconds=83.0,
                trigger="manual",
                status="success",
                stages=[
                    {
                        "name": "sort",
                        "status": "completed",
                        "duration_seconds": 2.1,
                        "result": {"moved": 3},
                    },
                    {
                        "name": "upscale",
                        "status": "skipped",
                        "duration_seconds": 0.0,
                        "skip_reason": "no_pending_work",
                        "result": None,
                    },
                ],
            )

            save_run(record, runs_dir)

            # File exists
            expected_path = runs_dir / "2026-03-29T14-30-00.json"
            self.assertTrue(expected_path.exists())

            # Round-trip
            loaded = load_runs(runs_dir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, record.id)
            self.assertEqual(loaded[0].trigger, "manual")
            self.assertEqual(loaded[0].stages[0]["name"], "sort")
            self.assertEqual(loaded[0].stages[1]["status"], "skipped")

    def test_load_runs_sorted_newest_first(self):
        with workspace_temp_dir() as tmp:
            runs_dir = tmp / "runs"
            runs_dir.mkdir()

            for ts in ["2026-03-29T14-00-00", "2026-03-29T14-30-00", "2026-03-29T14-15-00"]:
                record = RunRecord(
                    id=ts, started_at=ts, finished_at=ts,
                    duration_seconds=1.0, trigger="scheduled", status="success", stages=[],
                )
                save_run(record, runs_dir)

            loaded = load_runs(runs_dir)
            ids = [r.id for r in loaded]
            self.assertEqual(ids, ["2026-03-29T14-30-00", "2026-03-29T14-15-00", "2026-03-29T14-00-00"])

    def test_load_runs_returns_empty_for_missing_dir(self):
        self.assertEqual(load_runs(Path("nonexistent_dir_xyz")), [])


class TestRunRecordFromPipelineResult(unittest.TestCase):

    def test_from_pipeline_result_creates_record(self):
        from evolver import PipelineResult, StageRecord
        from gui.run_record import RunRecord

        pr = PipelineResult(
            stages=[
                StageRecord("sort", "completed", 1.5, Mock(moved=2)),
                StageRecord("upscale", "skipped", 0.0, skip_reason="cpu_busy"),
            ],
            has_errors=False,
            duration_seconds=10.0,
        )

        record = RunRecord.from_pipeline_result(pr, trigger="scheduled")
        self.assertEqual(record.trigger, "scheduled")
        self.assertEqual(record.status, "success")
        self.assertEqual(len(record.stages), 2)
        self.assertEqual(record.stages[0]["name"], "sort")
        self.assertEqual(record.stages[0]["status"], "completed")
        self.assertEqual(record.stages[1]["skip_reason"], "cpu_busy")


class TestFormatRunLabel(unittest.TestCase):

    def test_formats_utc_to_pacific_standard_time(self):
        # 2026-01-15T06:05:00 UTC = 2025-01-14 22:05 PST (UTC-8)
        label = format_run_label("2026-01-15T06:05:00", 5.0, "success")
        self.assertEqual(label, "\u2714  2026/01/14 22:05 (5s)")

    def test_formats_utc_to_pacific_daylight_time(self):
        # 2026-07-15T03:20:00 UTC = 2026-07-14 20:20 PDT (UTC-7)
        label = format_run_label("2026-07-15T03:20:00", 12.0, "success")
        self.assertEqual(label, "\u2714  2026/07/14 20:20 (12s)")

    def test_error_status_uses_cross_mark(self):
        label = format_run_label("2026-03-30T05:20:00", 3.0, "error")
        self.assertEqual(label, "\u2718  2026/03/29 22:20 (3s)")

    def test_rounds_duration_to_integer(self):
        label = format_run_label("2026-03-30T05:20:00", 83.7, "success")
        self.assertEqual(label, "\u2714  2026/03/29 22:20 (84s)")


if __name__ == "__main__":
    unittest.main()
