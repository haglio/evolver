"""What counts as a video in this library, and how to walk it.

``VIDEO_EXTENSIONS`` is read here rather than passed in: it is one repo-wide
answer to "what is a video", not something a caller varies, and it was being
threaded through eleven call sites and five identical one-line wrappers to say
so. The two functions that DO take it are the ones a caller genuinely narrows
-- the partial sweep, and the predicate it shares.
"""

from __future__ import annotations

import logging
from pathlib import Path

import config


def is_partial_video_path(path: Path) -> bool:
    return ".partial." in path.name.lower()


def is_finalized_video_file(path: Path, video_extensions: set[str]) -> bool:
    return path.is_file() and path.suffix.lower() in video_extensions and not is_partial_video_path(path)


def iter_finalized_videos(root: Path, video_extensions: set[str]):
    for path in root.rglob("*"):
        if is_finalized_video_file(path, video_extensions):
            yield path


def library_videos(root: Path):
    """Every finished video under *root*, at any depth, unordered."""
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def child_dirs(root: Path):
    """*root*'s immediate subdirectories, in name order — none when it is absent.

    Four stages walked the library's ``<source>/`` or ``<orientation>/`` level
    and three of them wrote this out identically; the fourth left off the guard
    and raised on a root that is not there yet.
    """
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            yield child


def remove_empty_dirs(root: Path) -> None:
    """Delete empty subdirectories under *root*, leaves first."""
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def remove_partial_video_files(root: Path, video_extensions: set[str], logger: logging.Logger) -> int:
    if not root.is_dir():
        return 0

    removed = 0
    for path in root.rglob("*"):
        if not (path.is_file() and is_partial_video_path(path) and path.suffix.lower() in video_extensions):
            continue
        try:
            path.unlink()
        except OSError:
            logger.exception("Failed to delete stale partial output: %s", path)
            continue
        removed += 1
    return removed
