from __future__ import annotations

import glob
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app_support.kino_folder import is_ai_video
from app_support.trash_names import name_before_trash
from app_support.video_names import strip_uniquifier

import config
from util import lanes, origenerator_gallery, script_library
from util.media_files import library_videos, retry_while_in_use
from util.origenerator_gallery import EVOLVER_UPSCALE
from util.sidecar import sidecar_folder, sidecar_path
from util.versions import sorted_stem_of

log = logging.getLogger(__name__)


def trash_dirs() -> tuple[Path, Path]:
    return tuple(lane.trash for lane in lanes.upscale_lanes())


def videos_in_trash() -> list[Path]:
    return [video for folder in trash_dirs()
            for video in sorted(library_videos(folder), key=lambda video: (video.name.lower(), video))]


def stems_in_trash() -> set[str]:
    return {Path(name_before_trash(video.name)).stem for video in videos_in_trash()}


@dataclass(frozen=True)
class InTrash:
    video: Path
    restores_to: Path | None
    upscaled_from: Path | None = None


def non_ai_videos_in_trash() -> list[Path]:
    _, genau_trash = trash_dirs()
    ai = lanes.in_trash(delivered) if (delivered := lanes.genau_delivery_dir()) else None
    return [video for video in videos_in_trash()
            if video.is_relative_to(genau_trash) and not (ai is not None and video.is_relative_to(ai))]


def non_ai_in_trash() -> list[InTrash]:
    return _marked(non_ai_videos_in_trash())



def marked_as(videos) -> list[InTrash]:
    held = set(videos_in_trash())
    return _marked([video for video in map(Path, videos) if video in held])


def _marked(videos: list[Path]) -> list[InTrash]:
    _, genau_trash = trash_dirs()
    sorted_copies = _sorted_copies_by_stem() if videos else {}
    return [_out_of_genau(video, genau_trash, sorted_copies) if video.is_relative_to(genau_trash)
            else _out_of_the_outbox(video, sorted_copies)
            for video in videos]


def _sorted_copies_by_stem() -> dict[str, list[Path]]:
    by_stem = defaultdict(list)
    for copy in library_videos(config.SORTED_DIR):
        by_stem[copy.stem].append(copy)
    return by_stem


def _out_of_the_outbox(video: Path, sorted_copies: dict[str, list[Path]]) -> InTrash:
    upscales = {spot: copy
                for copy in sorted_copies.get(sorted_stem_of(Path(name_before_trash(video.name)).stem), [])
                if (spot := lanes.upscale_filed_for(copy)) is not None}
    restores_to = _the_one_vacant(list(upscales)) or _the_one_vacant(_recorded_spots(video))
    return InTrash(video, restores_to, upscales.get(restores_to))


def _out_of_genau(video: Path, folder: Path, sorted_copies: dict[str, list[Path]]) -> InTrash:
    lane = config.SORTED_DIR / config.GENAU_SOURCE
    left_in_the_lane = [copy
                        for copy in sorted_copies.get(sorted_stem_of(strip_uniquifier(video.stem)), [])
                        if copy.is_relative_to(lane)]
    flicks = lanes.genau_flicks_dir()
    return InTrash(video, _the_one_vacant([flicks / video.relative_to(folder)] if flicks else []),
                       left_in_the_lane[0] if len(left_in_the_lane) == 1 else None)


def _recorded_spots(video: Path) -> list[Path]:
    name = name_before_trash(video.name)
    non_ai = config.NON_AI_DIR
    records = sidecar_folder(non_ai)
    return [*_where_the_gallery_keeps(name, lanes.kino_upscales_dir()),
            *([] if records is None else
              [non_ai / record.parent.relative_to(records) / name
               for record in records.rglob(glob.escape(f"{Path(name).stem}.json"))])]


def _where_the_gallery_keeps(name: str, kino: Path) -> list[Path]:
    try:
        rows = origenerator_gallery.rows(("prompt_id", "output_files"), optional=(EVOLVER_UPSCALE,))
    except (FileNotFoundError, sqlite3.Error):
        return []
    return list(dict.fromkeys(place for row in rows for place in origenerator_gallery.places_of(row)
                              if place.name == name and place.is_relative_to(kino)))


def restore(marked: InTrash) -> None:
    if marked.restores_to is None:
        raise ValueError(f"Nothing says where {marked.video.name} was sent to Trash from")
    if marked.restores_to.exists():
        raise FileExistsError(f"Something else is at {marked.restores_to} now")
    marked.restores_to.parent.mkdir(parents=True, exist_ok=True)
    retry_while_in_use(lambda: marked.video.rename(marked.restores_to))
    log.info("Restored %s  ->  %s", marked.video, marked.restores_to)
    for script in script_library.scripts_held_for(marked.video):
        home = script_library.script_path_for_video(marked.restores_to)
        if not home.exists():
            home.parent.mkdir(parents=True, exist_ok=True)
            script.rename(home)
            script_library.carry_mark(script, home)


def delete_permanently(marked: InTrash) -> None:
    for gone in (marked.upscaled_from, marked.video, _own_record(marked), _sound_only_it_plays(marked)):
        if gone is not None and gone.exists():
            retry_while_in_use(gone.unlink)
            log.info("Deleted permanently: %s", gone)
    for script in script_library.scripts_held_for(marked.video, marked.restores_to, marked.upscaled_from):
        script_library.delete_script(script)
        log.info("Deleted permanently: %s", script)


def _own_record(marked: InTrash) -> Path | None:
    home = marked.restores_to
    return None if home is None or is_ai_video(home) else sidecar_path(home)


def _sound_only_it_plays(marked: InTrash) -> Path | None:
    _, genau_trash = trash_dirs()
    if not marked.video.is_relative_to(genau_trash):
        return None
    if any(video.stem == marked.video.stem and video != marked.video
           for video in library_videos(config.GENAU_DIR)):
        return None
    return config.GENAU_AUDIO_DIR / f"{marked.video.stem}.mp3"


def _the_one_vacant(spots: list[Path]) -> Path | None:
    vacant = [spot for spot in spots if not spot.exists()]
    return vacant[0] if len(vacant) == 1 else None
