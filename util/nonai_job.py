"""The three JSON files the non-AI upscale stage keeps its state in.

One in-flight record (which encode is running, since when, and whether it is
frozen), one attempt counter per clip (so a video that fails repeatedly stops
being retried), and one cooldown stamp (when the last encode ended, so an
unattended night does not run the box flat out end to end).

Every function takes the file it works on rather than reading ``config``: the
stage owns which paths these are, and a caller — a test, or a second entry
point — can point them anywhere.  All three readers are tolerant by design.
The record is the on-disk contract with a live multi-hour encode and the sync
service covering the project tree has renamed it mid-run, so a missing or
half-written file has to read as "no state", never as a crash that would strand
the encode it describes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def load_job(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_job(path: Path, job: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")


def clear_job(path: Path) -> None:
    path.unlink(missing_ok=True)


def attempts_of(path: Path, key: str) -> int:
    return _load_attempts(path).get(key, 0)


def bump_attempts(path: Path, key: str) -> None:
    attempts = _load_attempts(path)
    attempts[key] = attempts.get(key, 0) + 1
    _save_attempts(path, attempts)


def clear_attempts(path: Path, key: str) -> None:
    attempts = _load_attempts(path)
    if attempts.pop(key, None) is not None:
        _save_attempts(path, attempts)


def _load_attempts(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_attempts(path: Path, attempts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attempts, indent=2), encoding="utf-8")


def last_encode_ended_at(path: Path) -> float:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    ended_at = payload.get("ended_at", 0.0) if isinstance(payload, dict) else 0.0
    return ended_at if isinstance(ended_at, (int, float)) else 0.0


def stamp_encode_ended(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ended_at": time.time()}), encoding="utf-8")
