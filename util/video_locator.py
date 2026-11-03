from __future__ import annotations

import math
from collections import defaultdict
from itertools import chain
from pathlib import Path

from app_support.video_names import strip_processing_suffixes

import config
from util import ffprobe
from util.media_files import file_size, is_finalized_video_file, library_videos
from util.nonai_library import bucket_of
from util.trash_folders import trash_dirs


def build_index() -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    root = config.VIDEO_SEARCH_ROOT
    if not root.is_dir():
        return index
    left_out = trash_dirs()
    for video_path in chain(library_videos(root), library_videos(config.GENAU_DIR)):
        if any(video_path.is_relative_to(folder) for folder in left_out):
            continue
        index[video_path.name.lower()].append(video_path)
    return index


def relocate(was_at: Path, index: dict[str, list[Path]]) -> Path | None:
    matches = index.get(was_at.name.lower(), [])
    return matches[0] if len(matches) == 1 else None


def another_version_of(was_at: Path, index: dict[str, list[Path]]) -> Path | None:
    bucket = bucket_of(was_at)
    if bucket is None:
        return None
    original = strip_processing_suffixes(was_at.stem).casefold()
    versions = [
        video for videos in index.values() for video in videos
        if strip_processing_suffixes(video.stem).casefold() == original
        and bucket_of(video) == bucket
    ]
    return min(versions, key=lambda video: (file_size(video), str(video))) if versions else None


def renamed_in_place(was_at: Path, fingerprint: tuple[float, int]) -> Path | None:
    matches = [
        candidate
        for candidate in sorted(was_at.parent.glob("*"))
        if is_finalized_video_file(candidate)
        and _same_footage(ffprobe.frame_fingerprint(candidate), fingerprint)
    ]
    return matches[0] if len(matches) == 1 else None


def _same_footage(candidate: tuple[float, int] | None, wanted: tuple[float, int]) -> bool:
    if candidate is None:
        return False
    return candidate[1] == wanted[1] and math.isclose(candidate[0], wanted[0], rel_tol=1e-6)
