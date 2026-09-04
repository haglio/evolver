import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from unittest.mock import Mock, patch

from tests.temp_helpers import make_run_record, workspace_temp_dir

from gui.run_record import (
    RunRecord, format_run_label, load_runs, result_to_dict, save_run,
)


@dataclass
class _StageOutcome:
    """A stand-in stage result shaped like the real ones: counters plus paths.

    A real dataclass, not a Mock -- asdict() raises on a Mock, so the old test
    only ever exercised the repr fallback while claiming to pin the Path
    conversion.
    """
    moved: int = 0
    moved_files: list[Path] = dataclass_field(default_factory=list)


class TestResultToDict:

    def test_converts_a_dataclasss_path_fields_to_strings(self):
        result = _StageOutcome(
            moved=2, moved_files=[Path("C:/videos/a.mp4"), Path("C:/videos/b.mp4")],
        )
        d = result_to_dict(result)
        assert d == {
            "moved": 2,
            "moved_files": [str(Path("C:/videos/a.mp4")), str(Path("C:/videos/b.mp4"))],
        }

    def test_an_unconvertible_result_falls_back_to_its_repr(self):
        # The safety net the old Mock-based test was actually exercising:
        # a bare object() has no __dict__ and is no dataclass, so both
        # conversion strategies raise and the repr fallback answers.
        d = result_to_dict(object())
        assert list(d) == ["repr"]

    def test_returns_none_for_none(self):
        assert result_to_dict(None) is None


class TestRunRecordRoundTrip:

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
            assert expected_path.exists()

            # Round-trip
            loaded = load_runs(runs_dir)
            assert len(loaded) == 1
            assert loaded[0].id == record.id
            assert loaded[0].trigger == "manual"
            assert loaded[0].stages[0]["name"] == "sort"
            assert loaded[0].stages[1]["status"] == "skipped"

    def test_a_stage_result_carrying_paths_still_saves(self):
        """What stops every scheduled run failing to record: sort.run()'s
        moved_files are Path objects, and json.dumps raises on a Path --
        the conversion has to happen on the way into the record."""
        from evolver import PipelineResult, StageRecord

        pipeline_result = PipelineResult(
            stages=[StageRecord(
                "sort", "completed", 1.5,
                _StageOutcome(moved=1, moved_files=[Path("C:/videos/a.mp4")]),
            )],
            has_errors=False,
            duration_seconds=10.0,
        )
        record = RunRecord.from_pipeline_result(pipeline_result, trigger="scheduled")

        with workspace_temp_dir() as tmp:
            runs_dir = tmp / "runs"
            save_run(record, runs_dir)  # json.dumps on the real payload shape
            loaded = load_runs(runs_dir)

        assert loaded[0].stages[0]["result"]["moved_files"] == [str(Path("C:/videos/a.mp4"))]

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
            assert ids == ["2026-03-29T14-30-00", "2026-03-29T14-15-00", "2026-03-29T14-00-00"]

    def test_load_runs_returns_empty_for_missing_dir(self):
        assert load_runs(Path("nonexistent_dir_xyz")) == []


class TestLoadingRecordsTheDataclassDoesNotFullyDescribe:
    """One added field must not take the whole history down with it.

    ``RunRecord(**data)`` inside a bare ``except Exception: continue`` meant a
    record carrying a key the dataclass does not declare vanished with no word
    -- so adding one field to the format silently emptied the history list and
    the stats chart of every run written since, and so did one truncated file.
    """

    def _record(self, run_id, **extra):
        return {
            "id": run_id,
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:00:05",
            "duration_seconds": 5.0,
            "trigger": "manual",
            "status": "success",
            "stages": [],
            **extra,
        }

    def test_a_key_the_dataclass_does_not_declare_is_dropped_not_the_record(self):
        with workspace_temp_dir() as root:
            (root / "a.json").write_text(json.dumps(self._record("a")), encoding="utf-8")
            (root / "b.json").write_text(
                json.dumps(self._record("b", notes="a field added later")),
                encoding="utf-8",
            )

            records = load_runs(root)

            assert [r.id for r in records] == ["b", "a"]

    def test_a_file_written_half_way_is_skipped_and_named(self, caplog):
        with workspace_temp_dir() as root:
            (root / "a.json").write_text(json.dumps(self._record("a")), encoding="utf-8")
            (root / "b.json").write_text('{"id": "b", "started_at":', encoding="utf-8")

            with caplog.at_level(logging.WARNING):
                records = load_runs(root)

            assert [r.id for r in records] == ["a"]
            assert any("b.json" in record.getMessage() for record in caplog.records)

    def test_a_record_missing_a_field_the_dataclass_requires_is_named_too(self, caplog):
        with workspace_temp_dir() as root:
            (root / "a.json").write_text(json.dumps({"id": "a"}), encoding="utf-8")

            with caplog.at_level(logging.WARNING):
                records = load_runs(root)

            assert records == []
            assert any("a.json" in record.getMessage() for record in caplog.records)


class TestLoadingOnlyTheNewest:
    """Nothing prunes the runs directory, and the main window reads it on the
    GUI thread after every run."""

    def _write(self, root, run_id):
        (root / f"{run_id}.json").write_text(json.dumps({
            "id": run_id, "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:00:05", "duration_seconds": 5.0,
            "trigger": "manual", "status": "success", "stages": [],
        }), encoding="utf-8")

    def test_a_limit_takes_the_newest_that_many(self):
        with workspace_temp_dir() as root:
            for run_id in ("2026-01-01T00-00-00", "2026-01-02T00-00-00",
                           "2026-01-03T00-00-00"):
                self._write(root, run_id)

            records = load_runs(root, limit=2)

            assert [r.id for r in records] == ["2026-01-03T00-00-00",
                                               "2026-01-02T00-00-00"]

    def test_no_limit_reads_them_all(self):
        with workspace_temp_dir() as root:
            for run_id in ("2026-01-01T00-00-00", "2026-01-02T00-00-00"):
                self._write(root, run_id)

            assert len(load_runs(root)) == 2

    def test_the_limit_is_applied_before_any_file_is_opened(self):
        """The whole point: a run's file is named for the moment it started, so
        newest-first is the reverse of their order and picking the newest N
        costs one directory listing rather than parsing the lot."""
        with workspace_temp_dir() as root:
            for day in range(1, 6):
                self._write(root, f"2026-01-0{day}T00-00-00")
            opened = []
            real_read_text = Path.read_text

            def counting_read_text(self, *args, **kwargs):
                opened.append(self.name)
                return real_read_text(self, *args, **kwargs)

            with patch.object(Path, "read_text", counting_read_text):
                load_runs(root, limit=2)

            assert opened == ["2026-01-05T00-00-00.json", "2026-01-04T00-00-00.json"]


class TestRunRecordFromPipelineResult:

    def test_from_pipeline_result_creates_record(self):
        from evolver import PipelineResult, StageRecord

        pr = PipelineResult(
            stages=[
                StageRecord("sort", "completed", 1.5, Mock(moved=2)),
                StageRecord("upscale", "skipped", 0.0, skip_reason="cpu_busy"),
            ],
            has_errors=False,
            duration_seconds=10.0,
        )

        record = RunRecord.from_pipeline_result(pr, trigger="scheduled")
        assert record.trigger == "scheduled"
        assert record.status == "success"
        assert len(record.stages) == 2
        assert record.stages[0]["name"] == "sort"
        assert record.stages[0]["status"] == "completed"
        assert record.stages[1]["skip_reason"] == "cpu_busy"

    def test_started_at_is_the_start_and_finished_at_is_the_finish(self):
        """Both used to be the finish. So every view that trusts the name was
        wrong by the run's whole duration -- and at the 660-second watchdog
        ceiling that is eleven minutes, a full slot past the ten-minute
        schedule, which reads as belonging to the following tick."""
        from evolver import PipelineResult

        pr = PipelineResult(
            stages=[], has_errors=False, duration_seconds=699.7,
            started_at=datetime(2026, 7, 15, 3, 20, 0, tzinfo=timezone.utc),
        )

        record = RunRecord.from_pipeline_result(pr)

        assert record.started_at == "2026-07-15T03:20:00"
        assert record.finished_at == "2026-07-15T03:31:39"

    def test_the_start_is_the_pipelines_own_not_one_worked_out_afterwards(self):
        """The pipeline stamps its start as it begins and names its log banner
        with it. Recomputing the start here from the finish would drift from
        that banner by however long the record took to save, and a run whose
        record and banner disagree is one nothing can find in the log."""
        from evolver import PipelineResult
        from util import run_log

        started = datetime(2026, 7, 15, 3, 20, 0, tzinfo=timezone.utc)
        pr = PipelineResult(stages=[], has_errors=False, duration_seconds=699.7,
                            started_at=started)

        record = RunRecord.from_pipeline_result(pr)

        assert record.id == run_log.run_id(started)

    def test_the_log_mark_rides_along_onto_the_record(self):
        from evolver import PipelineResult

        pr = PipelineResult(stages=[], has_errors=False, duration_seconds=1.0,
                            log_start=1024, log_end=4096)

        record = RunRecord.from_pipeline_result(pr)

        assert (record.log_start, record.log_end) == (1024, 4096)

    def test_the_id_names_the_start_so_the_history_sorts_by_it(self):
        from evolver import PipelineResult

        pr = PipelineResult(stages=[], has_errors=False, duration_seconds=699.7)

        record = RunRecord.from_pipeline_result(pr)

        assert record.id == record.started_at.replace(":", "-")

    def test_a_record_with_no_mark_still_loads_back(self):
        """Every record on disk was written before the mark existed, so the two
        fields have to be optional at BOTH ends -- load_runs drops a record
        whose file is missing a field the dataclass requires."""
        with workspace_temp_dir() as runs_dir:
            (runs_dir / "2026-01-01T00-00-00.json").write_text(json.dumps({
                "id": "2026-01-01T00-00-00",
                "started_at": "2026-01-01T00:00:00",
                "finished_at": "2026-01-01T00:00:03",
                "duration_seconds": 3.0, "trigger": "scheduled",
                "status": "success", "stages": [],
            }), encoding="utf-8")

            loaded = load_runs(runs_dir)

        assert [r.log_start for r in loaded] == [None]


class TestFormatRunLabel:

    def test_formats_utc_to_pacific_standard_time(self):
        # 2026-01-15T06:05:00 UTC = 2025-01-14 22:05 PST (UTC-8)
        label = format_run_label("2026-01-15T06:05:00", 5.0)
        assert label == "2026/01/14 22:05 (5s)"

    def test_formats_utc_to_pacific_daylight_time(self):
        # 2026-07-15T03:20:00 UTC = 2026-07-14 20:20 PDT (UTC-7)
        label = format_run_label("2026-07-15T03:20:00", 12.0)
        assert label == "2026/07/14 20:20 (12s)"

    def test_rounds_duration_to_integer(self):
        label = format_run_label("2026-03-30T05:20:00", 83.7)
        assert label == "2026/03/29 22:20 (84s)"
