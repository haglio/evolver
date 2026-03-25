from __future__ import annotations

import logging
from pathlib import Path


def is_partial_video_path(path: Path) -> bool:
    return ".partial." in path.name.lower()


def is_finalized_video_file(path: Path, video_extensions: set[str]) -> bool:
    return path.is_file() and path.suffix.lower() in video_extensions and not is_partial_video_path(path)


def iter_finalized_videos(root: Path, video_extensions: set[str]):
    for path in root.rglob("*"):
        if is_finalized_video_file(path, video_extensions):
            yield path


def remove_partial_video_files(root: Path, video_extensions: set[str], logger: logging.Logger | None = None) -> int:
    if not root.is_dir():
        return 0

    removed = 0
    for path in root.rglob("*"):
        if not (path.is_file() and is_partial_video_path(path) and path.suffix.lower() in video_extensions):
            continue
        try:
            path.unlink()
        except OSError:
            if logger is not None:
                logger.exception("Failed to delete stale partial output: %s", path)
            continue
        removed += 1
    return removed
