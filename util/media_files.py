"""What counts as a video in this library, and how to walk it.

``VIDEO_EXTENSIONS`` is read here rather than passed in: it is one repo-wide
answer to "what is a video", not something a caller varies, and it was being
threaded through eleven call sites and five identical one-line wrappers to say
so.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path

import config

#: What a copy still being written wears, so a walk of the library goes past it
#: instead of taking half a video for a finished one. Published to the apps that
#: hand clips to this pipeline (``util.pipeline_contract``), which put it in the
#: names they copy under.
PARTIAL_MARKER = ".partial."


def partial_path(final: Path, stem: str) -> Path:
    return final.with_name(f"{stem}{PARTIAL_MARKER}{uuid.uuid4().hex}")


def partial_stem(partial: Path) -> str:
    return partial.name.split(PARTIAL_MARKER)[0]


def is_partial_path(path: Path) -> bool:
    return PARTIAL_MARKER in path.name.lower()


def _is_finished_video_name(path: Path) -> bool:
    return path.suffix.lower() in config.VIDEO_EXTENSIONS and not is_partial_path(path)


def is_finalized_video_file(path: Path) -> bool:
    return _is_finished_video_name(path) and path.is_file()


def library_videos(root: Path):
    """Every finished video under *root*, at any depth, unordered."""
    for path in root.rglob("*"):
        if is_finalized_video_file(path):
            yield path


def listed_videos(root: Path):
    """Every finished video under *root*, told apart by its folder's listing alone.

    For a cloud drive, where asking about one file can block for good while
    listing its folder answers at once.
    """
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from listed_videos(Path(entry.path))
        elif entry.is_file(follow_symlinks=False) and _is_finished_video_name(Path(entry.name)):
            yield Path(entry.path)


def file_size(path: Path) -> int:
    """*path*'s size in bytes, 0 when it cannot be read."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


# How a name collision is uniquified: "stem", then "stem (2)", "stem (3)"...
# It is a contract between two apps -- Origenerator applies it exporting into
# Evolver's inbox, Evolver applies it again delivering into Genau's folder, and
# Evolver strips it back off to match a library file to the row that produced
# it -- so the append and the strip are declared beside each other, where they
# cannot drift apart.
_UNIQUIFIER_RE = re.compile(r" \((\d+)\)$")


def unique_path(path: Path) -> Path:
    """*path* if the name is free, else the same name with a `` (2)``, `` (3)``…

    Flat folders here hold files put there by hand as well as generated ones,
    so a name can genuinely already be taken and a move must never quietly
    overwrite one.
    """
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def strip_uniquifier(stem: str) -> str:
    """*stem* without a trailing `` (2)``, and itself when it has none.

    The inverse of what :func:`unique_path` appends, used to match a library
    file back to the row that produced it.
    """
    return _UNIQUIFIER_RE.sub("", stem)


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


def remove_partial_files(root: Path, logger: logging.Logger, *, keep: Path | None = None) -> int:
    if not root.is_dir():
        return 0

    removed = 0
    for path in root.rglob("*"):
        if path == keep or not (is_partial_path(path) and path.is_file()):
            continue
        try:
            path.unlink()
        except OSError:
            logger.exception("Failed to delete stale partial output: %s", path)
            continue
        removed += 1
    return removed
