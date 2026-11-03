from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole

from util.json_reads import read_dict


def load_job(path: Path) -> dict | None:
    return read_dict(path) or None


def save_job(path: Path, job: dict) -> None:
    write_whole(path, json.dumps(job, indent=2))


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
