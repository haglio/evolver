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
from util import favs_csv
from util.json_store import atomic_write_text, read_dict_strict


def _no_fingerprint(path: Path) -> tuple[float, int] | None:
    """Most stores record only a path, so a renamed video is beyond their reach."""
    return None


@dataclass(frozen=True)
class ReferenceStore:
    label: str
    path: Path
    read: Callable[[Path], list[str]]
    rewrite: Callable[[Path, dict[str, str]], None]
    # (fps, frame count) of the video this file references, when it records one —
    # the only handle left once a rename has taken the filename away.
    fingerprint: Callable[[Path], tuple[float, int] | None] = _no_fingerprint


def discover() -> Iterator[ReferenceStore]:
    """Every store file that currently exists, in a stable order."""
    yield from _session_files(config.CLIPPER_SESSIONS_DIR, "*.json", "clipper session")
    yield from _session_files(config.SCRIPTURE_SESSIONS_DIR, "*.scripture", "scripture project")
    if config.FUN_TIME_WATCH_STATS_FILE.is_file():
        yield ReferenceStore(
            "fun time watch counts",
            config.FUN_TIME_WATCH_STATS_FILE,
            _read_json_object_keys,
            _rewrite_json_object_keys,
        )
    if config.FUN_TIME_FAVS_FILE.is_file():
        yield ReferenceStore(
            "fun time favorite",
            config.FUN_TIME_FAVS_FILE,
            _read_favorite_paths,
            _rewrite_favorite_paths,
        )


def _session_files(directory: Path, pattern: str, label: str) -> Iterator[ReferenceStore]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob(pattern)):
        yield ReferenceStore(
            label, path, _read_video_path_field, _rewrite_video_path_field, _session_fingerprint
        )


_VIDEO_PATH_FIELD = "video_path"


def _read_video_path_field(path: Path) -> list[str]:
    value = _load_json(path).get(_VIDEO_PATH_FIELD)
    return [value] if isinstance(value, str) and value else []


def _rewrite_video_path_field(path: Path, moves: dict[str, str]) -> None:
    payload = _load_json(path)
    payload[_VIDEO_PATH_FIELD] = moves[payload[_VIDEO_PATH_FIELD]]
    _write_json(path, payload)


def _session_fingerprint(path: Path) -> tuple[float, int] | None:
    """A session's own record of the footage it was cut against."""
    payload = _load_json(path)
    fps, total_frames = payload.get("fps"), payload.get("total_frames")
    if isinstance(fps, int | float) and isinstance(total_frames, int) and fps > 0 and total_frames > 0:
        return float(fps), total_frames
    return None


def _read_json_object_keys(path: Path) -> list[str]:
    return list(_load_json(path))


def _rewrite_json_object_keys(path: Path, moves: dict[str, str]) -> None:
    """Re-key in place, keeping Fun Time's ``path.strip().lower()`` normalization.

    A key written in any other case simply never matches again, so the counts
    would be stranded just as thoroughly as by the move itself.
    """
    payload = _load_json(path)
    _write_json(path, {moves.get(key, key).lower(): value for key, value in payload.items()})


def _read_favorite_paths(path: Path) -> list[str]:
    fieldnames, rows = favs_csv.read_rows(path)
    column = favs_csv.file_column_name(fieldnames)
    if column is None:
        return []
    return [str(local) for local in _favorite_locals(rows, column, path.parent).values()]


def _rewrite_favorite_paths(path: Path, moves: dict[str, str]) -> None:
    fieldnames, rows = favs_csv.read_rows(path)
    column = favs_csv.file_column_name(fieldnames)
    for index, local in _favorite_locals(rows, column, path.parent).items():
        moved_to = moves.get(str(local))
        if moved_to is not None:
            rows[index][column] = favs_csv.with_local_path(rows[index][column], Path(moved_to))
    favs_csv.write_rows(path, fieldnames, rows)


def _favorite_locals(rows: list[dict[str, str]], column: str, base_dir: Path) -> dict[int, Path]:
    """Every row that links to a local file, by row index."""
    found: dict[int, Path] = {}
    for index, row in enumerate(rows):
        local = favs_csv.local_path((row.get(column) or "").strip(), base_dir)
        if local is not None:
            found[index] = local
    return found


def _load_json(path: Path) -> dict:
    """Strict on purpose: these files belong to the sibling apps, so one this
    cannot read must stop the rewrite rather than be treated as empty and
    replaced with a new one."""
    return read_dict_strict(path)


def _write_json(path: Path, payload: dict) -> None:
    # newline="\n" because the app that owns this file wrote it that way.
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n", newline="\n")
