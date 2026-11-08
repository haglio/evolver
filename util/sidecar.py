from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app_support import favorites, video_ids
from app_support.json_store import locked_update, read_json_or_empty
from app_support.mirrored_tree import mirrored_path

import config


def sidecar_path(video: Path) -> Path:
    path = _mirrored(video, ".json")
    if path is None:
        raise ValueError(f"{video} is not in the video library")
    return path


def sidecar_folder(folder: Path) -> Path | None:
    return _mirrored(folder, folder.suffix)


def _video_roots() -> tuple[Path, Path]:
    return config.VIDEO_LIBRARY_DIR, config.VIDEO_SEARCH_ROOT


def _records_root() -> Path:
    return config.METADATA_DIR


def _mirrored(path: Path, suffix: str) -> Path | None:
    return mirrored_path(path, roots=_video_roots(), mirror_root=_records_root(), suffix=suffix)


def videos_by_id() -> dict[str, Path]:
    return video_ids.videos_by_id(((_records_root(), _video_roots()),))


def mark_favorite(video: Path, favorite: bool) -> bool:
    return favorites.mark(sidecar_path(video), favorite)


def library_favorites() -> list[favorites.Favorite]:
    return favorites.favorites_under(_records_root(), video_roots=_video_roots(),
                                     video_suffixes=sorted(config.VIDEO_EXTENSIONS))


def read(path: Path) -> dict:
    return read_json_or_empty(path)


def update(path: Path, change: Callable[[dict], dict | None]) -> dict | None:
    return locked_update(path, change)


WRONG_ACTION_FIELD = "wrong_action"
