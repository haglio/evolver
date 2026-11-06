from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole
from app_support.json_store import read_json

import config
from util import lanes, sidecar

GENAUMACHER_SESSION_VERSION = 1
SCRIPTURE_PROJECT_VERSION = 1

_WATCH_COUNTS = frozenset({"completions", "skips", "locks"})


def _no_fingerprint(_path: Path) -> tuple[float, int] | None:
    return None


def _nothing_to_check(_path: Path) -> str | None:
    return None


@dataclass(frozen=True)
class ReferenceStore:
    label: str
    path: Path
    _read: Callable[[Path], list[str]]
    _rewrite: Callable[[Path, dict[str, str]], None]
    _fingerprint: Callable[[Path], tuple[float, int] | None] = _no_fingerprint
    _shape: Callable[[Path], str | None] = _nothing_to_check
    any_version_will_do: bool = False

    def read(self) -> list[str]:
        return self._read(self.path)

    def rewrite(self, moves: dict[str, str]) -> None:
        self._rewrite(self.path, moves)

    def fingerprint(self) -> tuple[float, int] | None:
        return self._fingerprint(self.path)

    def shape_complaint(self) -> str | None:
        return self._shape(self.path)


def discover() -> Iterator[ReferenceStore]:
    yield from _session_files(
        config.GENAUMACHER_SESSIONS_DIR, "*.json", "Genaumacher session", GENAUMACHER_SESSION_VERSION
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
    yield from _clip_pairings()


def _clip_pairings() -> Iterator[ReferenceStore]:
    for video in lanes.non_ai_videos():
        path = sidecar.sidecar_path(video)
        if _read_paired_scene(path):
            yield ReferenceStore(
                "clip pairing", path, _read_paired_scene, _rewrite_paired_scene,
                any_version_will_do=True,
            )


def _read_paired_scene(path: Path) -> list[str]:
    scene = _pairing(sidecar.read(path)).get("full_video")
    return [scene] if isinstance(scene, str) and scene else []


def _rewrite_paired_scene(path: Path, moves: dict[str, str]) -> None:
    def follow_the_scene(payload: dict) -> dict | None:
        pairing = _pairing(payload)
        if pairing.get("full_video") not in moves:
            return None
        pairing["full_video"] = moves[pairing["full_video"]]
        return payload

    sidecar.update(path, follow_the_scene)


def _pairing(payload: dict) -> dict:
    clip = payload.get("clip")
    return clip if isinstance(clip, dict) else {}


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
    def complaint(path: Path) -> str | None:
        found = _load_json(path).get("version", version)
        return None if found == version else f"says version {found!r}, not {version}"

    return complaint


def _is_counts_by_path(path: Path) -> str | None:
    for key, value in _load_json(path).items():
        if not isinstance(value, dict) or not set(value) >= _WATCH_COUNTS:
            return f"{key!r} does not hold the watch counts this stage re-keys"
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
    payload = _load_json(path)
    fps, total_frames = payload.get("fps"), payload.get("total_frames")
    if isinstance(fps, int | float) and isinstance(total_frames, int) and fps > 0 and total_frames > 0:
        return float(fps), total_frames
    return None


def _read_json_object_keys(path: Path) -> list[str]:
    return list(_load_json(path))


def _rewrite_json_object_keys(path: Path, moves: dict[str, str]) -> None:
    payload = _load_json(path)
    _write_json(path, {moves.get(key, key).lower(): value for key, value in payload.items()})



def _load_json(path: Path) -> dict:
    return read_json(path)


def _write_json(path: Path, payload: dict) -> None:
    write_whole(path, json.dumps(payload, indent=2) + "\n", newline="\n")
