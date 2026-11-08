from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app_support import kino_folder

import config
from util import lanes
from util.media_files import remove_empty_dirs, remove_partial_files, retry_while_in_use

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MovedOut:
    moved: int = 0
    failed: int = 0


def move_into_the_lane_folders() -> MovedOut:
    outbox = kino_folder.retired_outbox_in(config.LIBRARY_ROOT)
    if not outbox.is_dir():
        return MovedOut()
    log.info("=== Moving what the retired %s holds into Kino's and Genau's folders ===", outbox)
    remove_partial_files(outbox, logger=log)
    inside = outbox.relative_to(config.VIDEO_LIBRARY_DIR)
    videos = MovedOut()
    for tree in (config.VIDEO_LIBRARY_DIR, config.METADATA_DIR,
                 config.SCRIPT_LIBRARY_DIR, config.GENERATED_SCRIPTS_DIR):
        moved = _move_everything_under(tree, tree / inside)
        videos = moved if tree == config.VIDEO_LIBRARY_DIR else videos
    log.info("Moved out of the retired outbox: %d, left there: %d", videos.moved, videos.failed)
    return videos


def _move_everything_under(tree: Path, retired: Path) -> MovedOut:
    if not retired.is_dir():
        return MovedOut()
    moved = failed = 0
    for held in sorted(path for path in retired.rglob("*") if path.is_file()):
        went = _where_it_went(config.VIDEO_LIBRARY_DIR / held.relative_to(tree))
        destination = None if went is None else tree / went.relative_to(config.VIDEO_LIBRARY_DIR)
        if _move(held, destination):
            moved += 1
        else:
            failed += 1
    remove_empty_dirs(retired)
    if retired.is_dir() and not any(retired.iterdir()):
        retired.rmdir()
    return MovedOut(moved, failed)


def _where_it_went(video: Path) -> Path | None:
    outbox = kino_folder.retired_outbox_in(config.LIBRARY_ROOT)
    match video.relative_to(outbox).parts:
        case ("upscaled_by_orientation", _orient, source, *rest) if rest and lanes.is_genau_lane(source):
            genau = lanes.genau_delivery_dir()
            return None if genau is None else genau.joinpath(*rest)
    return kino_folder.where_it_went(video, config.LIBRARY_ROOT, config.KINO_DIR)


def _move(held: Path, destination: Path | None) -> bool:
    if destination is None:
        log.error("NOWHERE TO MOVE (left where it is): %s", held)
        return False
    if destination.exists():
        log.error("ALREADY THERE (left where it is): %s  ->  %s", held, destination)
        return False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        retry_while_in_use(lambda: held.rename(destination))
    except OSError:
        log.error("COULD NOT MOVE (left for the next run): %s", held, exc_info=True)
        return False
    log.info("MOVED %s  ->  %s", held, destination)
    return True
