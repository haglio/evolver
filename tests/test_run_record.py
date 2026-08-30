import json
import logging
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from unittest.mock import Mock

from tests.temp_helpers import workspace_temp_dir

from gui.run_record import RunRecord, result_to_dict, save_run, load_runs, format_run_label


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
