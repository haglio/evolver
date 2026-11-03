from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import config
from util import run_log

log = logging.getLogger(__name__)


@dataclass
class RunRecord:
    id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    trigger: str
    status: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    log_start: int | None = None
    log_end: int | None = None

    @classmethod
    def from_pipeline_result(cls, result, trigger: str = "scheduled") -> RunRecord:
        started = result.started_at
        finished = started + timedelta(seconds=result.duration_seconds)
        run_id = run_log.run_id(started)
        started_at = started.strftime("%Y-%m-%dT%H:%M:%S")
        finished_at = finished.strftime("%Y-%m-%dT%H:%M:%S")

        stages = []
        for sr in result.stages:
            stage_dict: dict[str, Any] = {
                "name": sr.name,
                "status": sr.status,
                "duration_seconds": sr.duration_seconds,
                "result": result_to_dict(sr.result),
            }
            if sr.skip_reason:
                stage_dict["skip_reason"] = sr.skip_reason
            stages.append(stage_dict)

        return cls(
            id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=result.duration_seconds,
            trigger=trigger,
            status="error" if result.has_errors else "success",
            stages=stages,
            log_start=result.log_start,
            log_end=result.log_end,
        )


def utc_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


def in_display_zone(moment: datetime) -> datetime:
    return moment.astimezone(config.DISPLAY_TIMEZONE)


def format_run_label(started_at: str, duration_seconds: float) -> str:
    shown = in_display_zone(utc_time(started_at))
    return f"{shown.strftime('%Y/%m/%d %H:%M')} ({duration_seconds:.0f}s)"


def result_to_dict(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    try:
        if dataclasses.is_dataclass(result) and not isinstance(result, type):
            d = dataclasses.asdict(result)
        else:
            d = {k: v for k, v in vars(result).items() if not k.startswith("_")}
    except TypeError:
        log.warning("Stage result %r could not be described; keeping its repr.",
                    type(result).__name__)
        return {"repr": repr(result)}
    return _make_json_safe(d)


def _make_json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def save_run(record: RunRecord, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{record.id}.json"
    data = dataclasses.asdict(record)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def newest_runs(runs_dir: Path, count: int) -> list[RunRecord]:
    paths = sorted(_record_files(runs_dir), reverse=True)[:count]
    records = list(_read_records(paths))
    records.sort(key=lambda r: r.id, reverse=True)
    return records


def every_run(runs_dir: Path) -> Iterator[RunRecord]:
    return _read_records(sorted(_record_files(runs_dir)))


def _record_files(runs_dir: Path) -> list[Path]:
    return list(runs_dir.glob("*.json")) if runs_dir.is_dir() else []


def _read_records(paths: Iterable[Path]) -> Iterator[RunRecord]:
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = RunRecord(**{
                key: value for key, value in data.items()
                if key in RunRecord.__dataclass_fields__
            })
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            log.warning("Could not read run record %s; skipping it.", path,
                        exc_info=True)
            continue
        yield record
