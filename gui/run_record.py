"""Run record persistence — one JSON file per pipeline run."""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class RunRecord:
    """Serializable record of a single pipeline run."""
    id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    trigger: str  # "scheduled" or "manual"
    status: str   # "success" or "error"
    stages: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_pipeline_result(cls, result, trigger: str = "scheduled") -> RunRecord:
        """Build a RunRecord from a PipelineResult, called as the run ends.

        The start is derived from the finish rather than captured, so
        ``finished_at - started_at == duration_seconds`` holds by construction
        and the three cannot drift apart. Both used to be stamped with the
        finish, which made every view that trusts the name -- the history
        label, the chart's x axis -- wrong by the run's whole duration; at the
        660-second watchdog ceiling that is eleven minutes, a full slot past
        the ten-minute schedule, so a run read as belonging to the next tick.
        """
        now = datetime.now(timezone.utc)
        started = now - timedelta(seconds=result.duration_seconds)
        run_id = started.strftime("%Y-%m-%dT%H-%M-%S")
        started_at = started.strftime("%Y-%m-%dT%H:%M:%S")
        finished_at = now.strftime("%Y-%m-%dT%H:%M:%S")

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
        )


_PACIFIC = ZoneInfo("America/Los_Angeles")


def format_run_label(started_at: str, duration_seconds: float) -> str:
    """When a run started and how long it took, e.g. "2026/03/30 22:20 (5s)".

    Converts UTC *started_at* to Pacific time. The verdict is deliberately not
    in here: it rides beside this text as a colored mark (see
    :mod:`gui.status_symbols`), so coloring the verdict cannot color the
    timestamp along with it.
    """
    utc_dt = datetime.fromisoformat(started_at).replace(tzinfo=timezone.utc)
    pacific_dt = utc_dt.astimezone(_PACIFIC)
    return f"{pacific_dt.strftime('%Y/%m/%d %H:%M')} ({duration_seconds:.0f}s)"


def result_to_dict(result: Any) -> dict[str, Any] | None:
    """Convert a stage result object to a JSON-safe dict."""
    if result is None:
        return None
    try:
        if dataclasses.is_dataclass(result) and not isinstance(result, type):
            d = dataclasses.asdict(result)
        else:
            d = {k: v for k, v in vars(result).items() if not k.startswith("_")}
    except TypeError:
        # Something with no __dict__ to read -- a bare object, an int. Nothing
        # downstream reads this shape; it exists so one odd stage result cannot
        # cost the whole run its record.
        log.warning("Stage result %r could not be described; keeping its repr.",
                    type(result).__name__)
        return {"repr": repr(result)}
    return _make_json_safe(d)


def _make_json_safe(obj: Any) -> Any:
    """Recursively convert Path and other non-JSON types."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def save_run(record: RunRecord, runs_dir: Path) -> Path:
    """Write a RunRecord as JSON. Returns the file path."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{record.id}.json"
    data = dataclasses.asdict(record)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_runs(runs_dir: Path) -> list[RunRecord]:
    """Load all run records from a directory, newest first.

    Only the keys the dataclass declares are read off a record, so a field
    added to the format later does not make every record written since
    unreadable -- which, behind a bare ``except: continue``, emptied the
    history list and the stats chart with nothing said. A file that genuinely
    cannot be read is skipped and named in the log instead of vanishing.
    """
    if not runs_dir.is_dir():
        return []
    records = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append(RunRecord(**{
                key: value for key, value in data.items()
                if key in RunRecord.__dataclass_fields__
            }))
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            # AttributeError: valid JSON that is not an object, so .items() is
            # not there to call. TypeError: a record missing a field the
            # dataclass requires.
            log.warning("Could not read run record %s; skipping it.", path,
                        exc_info=True)
    records.sort(key=lambda r: r.id, reverse=True)
    return records
