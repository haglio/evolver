from __future__ import annotations

import contextlib
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import retried_while_held

import config

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


def kept_by_another_app(path: Path) -> bool:
    return any(path.is_relative_to(folder) for folder in config.kept_by_other_apps())


def _walked(root: Path):
    left_out = config.kept_by_other_apps()
    for folder, subfolders, names in root.walk():
        subfolders[:] = [name for name in subfolders if folder / name not in left_out]
        for name in names:
            yield folder / name


def library_videos(root: Path):
    for path in _walked(root):
        if is_finalized_video_file(path):
            yield path


def library_files(root: Path):
    for path in _walked(root):
        if path.is_file():
            yield path


def reachable(folder: Path) -> bool:
    try:
        with os.scandir(folder.anchor):
            return True
    except OSError:
        return False


def listed_videos(root: Path):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from listed_videos(Path(entry.path))
        elif entry.is_file(follow_symlinks=False) and _is_finished_video_name(Path(entry.name)):
            yield Path(entry.path)


_IN_USE_TRIES = 10
_IN_USE_WAIT_SECONDS = 0.2


def retry_while_in_use[T](action: Callable[[], T]) -> T:
    # Windows refuses to move or delete a file a player still has open.
    return retried_while_held(action, attempts=_IN_USE_TRIES, delay_s=_IN_USE_WAIT_SECONDS)


def take_its_place(new: Path, old: Path) -> None:
    try:
        dated = old.stat().st_mtime
    except FileNotFoundError:
        new.replace(old)
        return
    new.replace(old)
    os.utime(old, (time.time(), dated + 1))


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


_UNIQUIFIER_RE = re.compile(r" \((\d+)\)$")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def strip_uniquifier(stem: str) -> str:
    return _UNIQUIFIER_RE.sub("", stem)


def child_dirs(root: Path):
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            yield child


def remove_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            with contextlib.suppress(OSError):
                path.rmdir()


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
