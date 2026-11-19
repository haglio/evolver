from __future__ import annotations

from pathlib import Path

import config
from util import run_reads
from util.media_files import library_videos

_STAGE_DIGITS = "0123"


def is_stage_dir(path: Path) -> bool:
    return path.is_dir() and path.name[:1] in _STAGE_DIGITS


def holds_stages(folder: Path) -> bool:
    try:
        return any(is_stage_dir(child) for child in folder.iterdir())
    except OSError:
        return False


def _sub_libraries(folder: Path) -> list[Path]:
    try:
        children = sorted(folder.iterdir())
    except OSError:
        return []
    return [
        child
        for child in children
        if child.is_dir() and not is_stage_dir(child) and holds_stages(child)
    ]


def buckets() -> list[Path]:
    non_ai = config.NON_AI_DIR
    return run_reads.until_files_move(f"buckets {non_ai}", lambda: _buckets_in(non_ai))


def _buckets_in(non_ai: Path) -> list[Path]:
    if not non_ai.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(non_ai.iterdir()):
        if not child.is_dir():
            continue
        split = _sub_libraries(child)
        if split:
            found.extend(split)
        elif holds_stages(child):
            found.append(child)
    return found


def videos_by_bucket() -> dict[Path, list[Path]]:
    found: dict[Path, list[Path]] = {bucket: [] for bucket in buckets()}
    for video in run_reads.videos_in(config.NON_AI_DIR, library_videos):
        bucket = next((bucket for bucket in found if video.is_relative_to(bucket)), None)
        if bucket is not None:
            found[bucket].append(video)
    return found


def stage_dirs(parent: Path, digits: tuple[int, ...]) -> list[tuple[int, Path]]:
    return [(int(child.name[:1]), child) for child in sorted(parent.iterdir())
            if child.is_dir() and child.name[:1].isdigit() and int(child.name[:1]) in digits]


def bucket_of(video: Path) -> Path | None:
    try:
        relative = video.relative_to(config.NON_AI_DIR)
    except ValueError:
        return None
    folder = config.NON_AI_DIR
    for part in relative.parts[:-1]:
        folder = folder / part
        if _sub_libraries(folder):
            continue
        if holds_stages(folder):
            return folder
    return None
