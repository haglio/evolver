"""The files across the suite that record a video's path, and how to repoint them.

Each store is one file holding references Evolver can break by moving a video.
``read`` reports the video paths it names; ``rewrite`` applies an old -> new
mapping in place. Neither ever drops a reference: a path Evolver cannot find a
new home for is left exactly as it was, for a human to judge.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class ReferenceStore:
    label: str
    path: Path
    read: Callable[[Path], list[str]]
    rewrite: Callable[[Path, dict[str, str]], None]


def discover() -> Iterator[ReferenceStore]:
    """Every store file that currently exists, in a stable order."""
    yield from _session_files(config.CLIPPER_SESSIONS_DIR, "*.json", "clipper session")


def _session_files(directory: Path, pattern: str, label: str) -> Iterator[ReferenceStore]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob(pattern)):
        yield ReferenceStore(label, path, _read_video_path_field, _rewrite_video_path_field)


_VIDEO_PATH_FIELD = "video_path"


def _read_video_path_field(path: Path) -> list[str]:
    value = _load_json(path).get(_VIDEO_PATH_FIELD)
    return [value] if isinstance(value, str) and value else []


def _rewrite_video_path_field(path: Path, moves: dict[str, str]) -> None:
    payload = _load_json(path)
    payload[_VIDEO_PATH_FIELD] = moves[payload[_VIDEO_PATH_FIELD]]
    _write_json(path, payload)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, payload: dict) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    temp_path.replace(path)
