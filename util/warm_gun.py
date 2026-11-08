from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes

JOURNAL_PATTERN = "*.jsonl"
FIELDS = ("t", "event", "path")
FAVORITE_EVENTS = {"favorite": True, "unfavorite": False}
PHONE_JOURNAL = "warm-gun-journal.jsonl"
PHONES_NAME_FOR_GENAUS_FLICKS_FOLDER = "clips"


@dataclass(frozen=True, order=True)
class Event:
    t: int
    event: str
    path: str


def read_journals(directories: Iterable[Path]) -> dict[str, list[Event]]:
    events: dict[str, set[Event]] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for journal in sorted(directory.glob(JOURNAL_PATTERN)):
            found = events.setdefault(journal.name, set())
            for line in journal.read_text(encoding="utf-8").splitlines():
                event = _event(line)
                if event is not None:
                    found.add(event)
    return {name: sorted(found) for name, found in sorted(events.items())}


def _event(line: str) -> Event | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    t, event, path = (record.get(field) for field in FIELDS)
    if isinstance(t, bool) or not isinstance(t, int | float):
        return None
    if not (isinstance(event, str) and event and isinstance(path, str) and path):
        return None
    return Event(int(t), event, path)


def library_video(journal_path: str) -> Path | None:
    parts = journal_path.replace("\\", "/").split("/")
    match parts:
        case ["1_sorted", source, orient, name]:
            return lanes.upscale_of(source, orient, Path(name).stem)
        case ["non_AI", *rest] if rest:
            return config.NON_AI_DIR.joinpath(*rest)
        case ["genau", folder_named, *inside] if inside:
            return _genau_flick(lanes.genau_flicks_dir(), folder_named, inside)
    named = config.LIBRARY_ROOT.joinpath(*parts)
    return named if any(named.is_relative_to(folder) for folder in lanes.upscale_folders()) else None


def _genau_flick(flicks_folder: Path | None, folder_named: str, inside: list[str]) -> Path | None:
    if flicks_folder is None or folder_named not in (flicks_folder.name, PHONES_NAME_FOR_GENAUS_FLICKS_FOLDER):
        return None
    named = flicks_folder.joinpath(*inside)
    if len(inside) == 1 and not named.exists():
        found = list(flicks_folder.rglob(inside[0])) if flicks_folder.is_dir() else []
        if len(found) == 1:
            return found[0]
    return named


def played_video(journal_path: str) -> Path | None:
    match journal_path.replace("\\", "/").split("/"):
        case ["1_sorted", source, orient, name]:
            return config.SORTED_DIR.joinpath(source, orient, name)
    return library_video(journal_path)
