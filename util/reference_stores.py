"""The files across the suite that record a video's path, and how to repoint them.

Each store is one file holding references Evolver can break by moving a video.
``read`` reports the video paths it names; ``rewrite`` applies an old -> new
mapping in place. Neither ever drops a reference: a path Evolver cannot find a
new home for is left exactly as it was, for a human to judge.

Every one of these files belongs to another repo, and none of those repos hears
about this one -- so before rewriting one, ``shape_complaint`` asks whether it
is still the shape this stage was written against, and a file that is not is
left alone and reported. Clipper and Scripture each stamp a version their own
tests hold. Fun Time's watch counts carry none and cannot, since every key
there is a video path, so their shape is what is checked; its favorites file is
a spreadsheet whose header row is its version.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole

import config
from util import favs_csv
from util.json_reads import read_dict_strict

# The versions the two apps that stamp one write today, and the ones this stage
# was written against. A file saying anything else has moved on without this
# stage, and rewriting it blind is how one app corrupts another's saved work.
CLIPPER_SESSION_VERSION = 1
SCRIPTURE_PROJECT_VERSION = 1

# What one row of Fun Time's watch counts holds.
_WATCH_COUNTS = frozenset({"completions", "skips", "locks"})


def _no_fingerprint(_path: Path) -> tuple[float, int] | None:
    """Most stores record only a path, so a renamed video is beyond their reach."""
    return None


def _nothing_to_check(_path: Path) -> str | None:
    return None


@dataclass(frozen=True)
class ReferenceStore:
    """One file that names videos, and the three things this can ask of it.

    The readers are held as fields rather than as subclasses because what
    varies between stores is exactly these three functions and nothing else.
    They are private and reached through the methods below: a store handing its
    own path back into its own function -- ``store.read(store.path)`` -- is a
    hand-rolled vtable, and the one thing it makes possible is passing the
    wrong path.
    """

    label: str
    path: Path
    _read: Callable[[Path], list[str]]
    _rewrite: Callable[[Path, dict[str, str]], None]
    # (fps, frame count) of the video this file references, when it records one —
    # the only handle left once a rename has taken the filename away.
    _fingerprint: Callable[[Path], tuple[float, int] | None] = _no_fingerprint
    # What stops this file being rewritten, when something does.
    _shape: Callable[[Path], str | None] = _nothing_to_check

    def read(self) -> list[str]:
        """Every video path this file names."""
        return self._read(self.path)

    def rewrite(self, moves: dict[str, str]) -> None:
        """Apply an old -> new mapping in place, dropping nothing."""
        self._rewrite(self.path, moves)

    def fingerprint(self) -> tuple[float, int] | None:
        """The video's (fps, frame count), when this store records one."""
        return self._fingerprint(self.path)

    def shape_complaint(self) -> str | None:
        """Why this file must not be rewritten, or None when nothing says so.

        The repo that owns it does not know this one exists, so a format it
        changes arrives here as a file that still parses and still looks
        rewritable. This is what turns that into a refusal somebody reads
        rather than a rewrite nobody notices.
        """
        return self._shape(self.path)


def discover() -> Iterator[ReferenceStore]:
    """Every store file that currently exists, in a stable order."""
    yield from _session_files(
        config.CLIPPER_SESSIONS_DIR, "*.json", "clipper session", CLIPPER_SESSION_VERSION
    )
    yield from _session_files(
        config.SCRIPTURE_SESSIONS_DIR,
        "*.scripture",
        "scripture project",
        SCRIPTURE_PROJECT_VERSION,
    )
    if config.FUN_TIME_WATCH_STATS_FILE.is_file():
        yield ReferenceStore(
            "fun time watch counts",
            config.FUN_TIME_WATCH_STATS_FILE,
            _read_json_object_keys,
            _rewrite_json_object_keys,
            _shape=_is_counts_by_path,
        )
    if config.FUN_TIME_FAVS_FILE.is_file():
        yield ReferenceStore(
            "fun time favorite",
            config.FUN_TIME_FAVS_FILE,
            _read_favorite_paths,
            _rewrite_favorite_paths,
            _shape=_has_a_local_path_column,
        )


def _session_files(
    directory: Path, pattern: str, label: str, version: int
) -> Iterator[ReferenceStore]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob(pattern)):
        yield ReferenceStore(
            label,
            path,
            _read_video_path_field,
            _rewrite_video_path_field,
            _session_fingerprint,
            _stamped(version),
        )


def _stamped(version: int) -> Callable[[Path], str | None]:
    """A check that the file says it is the version this stage knows.

    A file written before its app stamped one is that first version, so silence
    reads as agreement -- every session and project on disk today is one of
    those.
    """

    def complaint(path: Path) -> str | None:
        found = _load_json(path).get("version", version)
        return None if found == version else f"says version {found!r}, not {version}"

    return complaint


def _is_counts_by_path(path: Path) -> str | None:
    """Fun Time's counts, checked by shape because they carry no version.

    They cannot carry one: every top-level key there is a video path, so a key
    holding a number would reach this stage as a video to go looking for.
    """
    for key, value in _load_json(path).items():
        if not isinstance(value, dict) or not set(value) >= _WATCH_COUNTS:
            return f"{key!r} does not hold the watch counts this stage re-keys"
    return None


def _has_a_local_path_column(path: Path) -> str | None:
    """The favorites file is a spreadsheet, and its header row is its version."""
    fieldnames, _rows = favs_csv.read_rows(path)
    if favs_csv.file_column_name(fieldnames) is None:
        return f"no column holding a local path, only {fieldnames}"
    return None


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
    return [str(video) for video in favs_csv.favorite_videos(path)]


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
    write_whole(path, json.dumps(payload, indent=2) + "\n", newline="\n")
