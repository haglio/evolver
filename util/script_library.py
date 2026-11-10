from __future__ import annotations

import shutil
from pathlib import Path

from app_support.funscript import (
    ACTIONS,
    AT,
    BOOKMARKS,
    CHAPTERS,
    DURATION,
    METADATA,
    actions_of,
    generated_mark_of,
    script_of,
)

import config
from util import provenance
from util.media_files import kept_by_another_app, remove_empty_dirs


def script_path_for_video(video: Path) -> Path:
    script = None if kept_by_another_app(video) else script_of(
        video, library=config.VIDEO_LIBRARY_DIR, scripts_tree=config.SCRIPT_LIBRARY_DIR)
    if script is None:
        raise ValueError(f"{video} is not in the video library")
    return script


def scripts_held_for(*videos: Path | None) -> list[Path]:
    held = []
    for video in filter(None, videos):
        try:
            script = script_path_for_video(video)
        except ValueError:
            continue
        if script.is_file():
            held.append(script)
    return held


def generated_mark(script: Path) -> Path | None:
    return generated_mark_of(script, scripts_tree=config.SCRIPT_LIBRARY_DIR, marks_tree=config.GENERATED_SCRIPTS_DIR)


def mark_generated(script: Path) -> None:
    mark = generated_mark(script)
    if mark is not None:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()


def is_marked_generated(script: Path) -> bool:
    mark = generated_mark(script)
    return mark is not None and mark.exists()


def copy_mark(script: Path, copied_to: Path) -> None:
    if is_marked_generated(script):
        mark_generated(copied_to)


def copy_script(script: Path, copied_to: Path) -> None:
    copied_to.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script, copied_to)
    copy_mark(script, copied_to)


def carry_mark(script: Path, moved_to: Path) -> None:
    copy_mark(script, moved_to)
    drop_mark(script)


def drop_mark(script: Path) -> None:
    mark = generated_mark(script)
    if mark is not None:
        mark.unlink(missing_ok=True)


def delete_script(script: Path) -> None:
    script.unlink()
    drop_mark(script)


def remove_empty_mark_folders() -> None:
    remove_empty_dirs(config.GENERATED_SCRIPTS_DIR)


def trim(script: dict, start_seconds: float, duration_seconds: float) -> dict:
    start_ms = round(start_seconds * 1000)
    end_ms = start_ms + round(duration_seconds * 1000)
    source = sorted(actions_of(script), key=lambda action: action[AT])

    inside = [action for action in source if start_ms <= action[AT] <= end_ms]
    before = [action for action in source if action[AT] < start_ms]
    if before and (not inside or inside[0][AT] != start_ms):
        inside.insert(0, {**before[-1], AT: start_ms})

    actions = [{**action, AT: action[AT] - start_ms} for action in inside]
    trimmed = {**script, ACTIONS: actions}

    metadata = script.get(METADATA)
    if isinstance(metadata, dict):
        trimmed[METADATA] = _retime_metadata(metadata, duration_seconds)
    return trimmed


def place(script: dict, start_seconds: float, duration_seconds: float) -> dict:
    start_ms = round(start_seconds * 1000)
    actions = [
        {**action, AT: action[AT] + start_ms}
        for action in sorted(actions_of(script), key=lambda action: action[AT])
    ]
    placed = {**script, ACTIONS: actions}

    metadata = script.get(METADATA)
    if isinstance(metadata, dict):
        placed[METADATA] = _retime_metadata(metadata, duration_seconds)
    return placed


def stamped_in_its_own_metadata(script: dict, act: str) -> dict:
    metadata = script.get(METADATA)
    metadata = metadata if isinstance(metadata, dict) else {}
    return {**script, METADATA: provenance.recorded(metadata, act, provenance.by_evolver())}


def _retime_metadata(metadata: dict, duration_seconds: float) -> dict:
    retimed = dict(metadata)
    if DURATION in retimed:
        retimed[DURATION] = int(duration_seconds)
    for absolute in (BOOKMARKS, CHAPTERS):
        if absolute in retimed:
            retimed[absolute] = []
    return retimed
