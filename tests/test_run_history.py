from __future__ import annotations

from datetime import UTC, datetime

from gui.run_history import RunHistory
from gui.run_record import save_run
from tasks.stages import ALL_STAGES
from tests.temp_helpers import make_run_record, workspace_temp_dir


def _run(started_at: str, **seconds_by_stage: float):
    return make_run_record(
        id=started_at.replace(":", "-"),
        started_at=started_at,
        stages=[{"name": stage, "status": "completed", "duration_seconds": seconds}
                for stage, seconds in seconds_by_stage.items()],
    )


def _row(history: RunHistory, stage: str) -> list[float]:
    return history.durations[ALL_STAGES.index(stage)].tolist()


def test_each_stage_holds_what_it_took_in_every_run_oldest_first():
    history = RunHistory.of([
        _run("2026-07-15T03:40:00", sort=6.0),
        _run("2026-07-15T03:20:00", sort=2.0),
        _run("2026-07-15T03:30:00", sort=4.0),
    ])

    assert _row(history, "sort") == [2.0, 4.0, 6.0]


def test_a_run_starts_at_the_moment_its_record_names_which_is_utc():
    history = RunHistory.of([_run("2026-07-15T03:20:00", sort=2.0)])

    assert history.started.tolist() == [datetime(2026, 7, 15, 3, 20, tzinfo=UTC).timestamp()]


def test_a_stage_a_run_never_reached_took_no_time():
    history = RunHistory.of([_run("2026-07-15T03:20:00", sort=2.0)])

    assert _row(history, "metadata") == [0.0]


def test_a_stage_since_taken_out_of_the_pipeline_is_passed_over():
    history = RunHistory.of([_run("2026-07-15T03:20:00", sort=2.0, retired_stage=9.0)])

    assert history.durations.sum() == 2.0


def test_reading_a_runs_directory_charts_every_run_on_record_oldest_first():
    with workspace_temp_dir() as runs_dir:
        for started, seconds in (("2026-07-15T03:30:00", 4.0), ("2026-07-15T03:20:00", 2.0)):
            save_run(_run(started, sort=seconds), runs_dir)

        history = RunHistory.read(runs_dir)

    assert _row(history, "sort") == [2.0, 4.0]


def test_a_run_whose_start_cannot_be_read_is_left_out_rather_than_dated_wrongly():
    history = RunHistory.of([
        _run("2026-07-15T03:20:00", sort=2.0),
        _run("not a moment", sort=9.0),
    ])

    assert _row(history, "sort") == [2.0]
