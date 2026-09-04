"""Warm Gun's journal: one JSON line per event on the phone, each naming its
video by the lane it was played from — ``1_sorted/<source>/<orientation>/x.mp4``,
``non_AI/<bucket>/…`` or ``genau/clips/x.mp4``."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import config
from util.sidecar import upscaled_video_path

JOURNAL_PATTERN = "*.jsonl"


@dataclass(frozen=True, order=True)
class Event:
    t: int
    event: str
    path: str


def read_journal(directories: Iterable[Path]) -> list[Event]:
    """Every event the journals under *directories* record, in time order.

    A set, so a line reached twice — the same journal read through two folders,
    or the phone re-uploading its whole history — counts once.
    """
    events: set[Event] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for journal in sorted(directory.glob(JOURNAL_PATTERN)):
            for line in journal.read_text(encoding="utf-8").splitlines():
                event = _event(line)
                if event is not None:
                    events.add(event)
    return sorted(events)


def _event(line: str) -> Event | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    t, event, path = record.get("t"), record.get("event"), record.get("path")
    if isinstance(t, bool) or not isinstance(t, int | float):
        return None
    if not (isinstance(event, str) and event and isinstance(path, str) and path):
        return None
    return Event(int(t), event, path)


def library_video(journal_path: str) -> Path | None:
    lane, *rest = journal_path.replace("\\", "/").split("/")
    if lane == "1_sorted" and len(rest) == 3:
        source, orient, name = rest
        return upscaled_video_path(source, orient, Path(name).stem)
    if lane == "non_AI" and rest:
        return config.NON_AI_DIR.joinpath(*rest)
    if lane == "genau" and len(rest) == 2 and rest[0] == "clips":
        return config.GENAU_CLIPS_DIR / rest[1]
    return None


def played_video(journal_path: str) -> Path | None:
    lane, *rest = journal_path.replace("\\", "/").split("/")
    if lane == "1_sorted" and len(rest) == 3:
        return config.SORTED_DIR.joinpath(*rest)
    return library_video(journal_path)
