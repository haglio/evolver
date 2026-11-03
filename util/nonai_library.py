from __future__ import annotations

from pathlib import Path

import config

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
    if not config.NON_AI_DIR.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(config.NON_AI_DIR.iterdir()):
        if not child.is_dir():
            continue
        split = _sub_libraries(child)
        if split:
            found.extend(split)
        elif holds_stages(child):
            found.append(child)
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
