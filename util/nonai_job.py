from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole

from util import processes
from util.json_reads import read_dict


class Job:
    def __init__(self, fields: dict) -> None:
        self._fields = fields

    @classmethod
    def started(cls, *, pid: int, source: Path | str, tmp: Path | str, out: Path | str,
                expected_duration: float, started_at: float, provenance: dict,
                on_request: bool = False) -> Job:
        fields = {"pid": pid, "source": str(source), "tmp": str(tmp), "out": str(out),
                  "expected_duration": expected_duration, "started_at": started_at,
                  "provenance": provenance}
        if on_request:
            fields["on_request"] = True
        return cls(fields)

    @classmethod
    def adopted(cls, *, pid: int, source: Path, tmp: Path, out: Path, expected_duration: float,
                started_at: float, provenance: dict) -> Job:
        return cls({"pid": pid, "source": str(source), "tmp": str(tmp), "out": str(out),
                    "expected_duration": expected_duration, "started_at": started_at,
                    "suspended": False, "suspended_at": 0.0, "suspended_seconds": 0.0,
                    "provenance": provenance})

    def fields(self) -> dict:
        return dict(self._fields)

    @property
    def pid(self) -> int:
        return self._fields.get("pid") or 0

    @property
    def source(self) -> Path:
        return Path(self._fields.get("source", ""))

    @property
    def tmp(self) -> Path:
        return Path(self._fields.get("tmp", ""))

    @property
    def out(self) -> Path:
        return Path(self._fields.get("out", ""))

    @property
    def expected_duration(self) -> float:
        return self._fields.get("expected_duration") or 0.0

    @property
    def provenance(self) -> dict | None:
        return self._fields.get("provenance") or None

    @property
    def suspended(self) -> bool:
        return bool(self._fields.get("suspended"))

    @property
    def on_request(self) -> bool:
        return bool(self._fields.get("on_request"))

    def is_running(self) -> bool:
        return bool(self.pid) and processes.is_running(self.pid)

    def active_runtime(self, *, now: float) -> float:
        suspended = self._fields.get("suspended_seconds", 0.0)
        if self.suspended and self._fields.get("suspended_at"):
            suspended += now - self._fields["suspended_at"]
        return now - self._fields.get("started_at", now) - suspended

    def suspend(self, *, now: float) -> None:
        self._fields["suspended"] = True
        self._fields["suspended_at"] = now

    def resume(self, *, now: float) -> None:
        paused_for = now - self._fields.get("suspended_at", now)
        self._fields["suspended_seconds"] = self._fields.get("suspended_seconds", 0.0) + paused_for
        self._fields["suspended"] = False
        self._fields["suspended_at"] = 0.0

    def ask_for(self) -> None:
        self._fields["on_request"] = True

    def withdraw_the_ask(self) -> bool:
        return bool(self._fields.pop("on_request", None))


def load_job(path: Path) -> Job | None:
    fields = read_dict(path)
    return Job(fields) if fields else None


def save_job(path: Path, job: Job) -> None:
    write_whole(path, json.dumps(job.fields(), indent=2))


def clear_job(path: Path) -> None:
    path.unlink(missing_ok=True)


def attempts_of(path: Path, key: str) -> int:
    return read_dict(path).get(key, 0)


def bump_attempts(path: Path, key: str) -> None:
    attempts = read_dict(path)
    attempts[key] = attempts.get(key, 0) + 1
    write_whole(path, json.dumps(attempts, indent=2))


def clear_attempts(path: Path, key: str) -> None:
    attempts = read_dict(path)
    if attempts.pop(key, None) is not None:
        write_whole(path, json.dumps(attempts, indent=2))


def last_encode_ended_at(path: Path) -> float:
    ended_at = read_dict(path).get("ended_at", 0.0)
    return ended_at if isinstance(ended_at, (int, float)) else 0.0


def stamp_encode_ended(path: Path) -> None:
    write_whole(path, json.dumps({"ended_at": time.time()}))


@dataclass(frozen=True)
class Request:
    video: str
    held_back: str = ""


def load_request(path: Path) -> Request | None:
    payload = read_dict(path)
    video, held_back = payload.get("video"), payload.get("held_back")
    if not isinstance(video, str) or not video:
        return None
    return Request(video, held_back if isinstance(held_back, str) else "")


def save_request(path: Path, request: Request) -> None:
    write_whole(path, json.dumps({"video": request.video, "held_back": request.held_back}))


def clear_request(path: Path) -> None:
    path.unlink(missing_ok=True)
