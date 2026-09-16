"""The three JSON files the non-AI upscale stage keeps its state in.

One in-flight record (which encode is running, since when, and whether it is
frozen), one attempt counter per clip (so a video that fails repeatedly stops
being retried), and one cooldown stamp (when the last encode ended, so an
unattended night does not run the machine flat out end to end).

Every function takes the file it works on rather than reading ``config``: the
stage owns which paths these are, and a caller — a test, or a second entry
point — can point them anywhere.  Every reader is tolerant by design.
The record is the on-disk contract with a live multi-hour encode and the sync
service covering the project tree has renamed it mid-run, so a missing or
half-written file has to read as "no state", never as a crash that would strand
the encode it describes.  Every writer lands its file whole, because the GUI's
presence poll and a pipeline tick read the record from two threads.
"""

from __future__ import annotations

import json
import time
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
