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


@dataclass(frozen=True)
class _Library:
    root: Path
    videos: Path
    mirrors: tuple[Path, ...]
    kino: Path

    @classmethod
    def configured(cls) -> _Library:
        return cls(config.LIBRARY_ROOT, config.VIDEO_LIBRARY_DIR,
                   (config.METADATA_DIR, config.SCRIPT_LIBRARY_DIR, config.GENERATED_SCRIPTS_DIR),
                   config.KINO_DIR)

    @property
    def outbox(self) -> Path:
        return kino_folder.retired_outbox_in(self.root)

    def where_it_went(self, video: Path) -> Path | None:
        match video.relative_to(self.outbox).parts:
            case ("upscaled_by_orientation", _orient, source, *rest) if rest and lanes.is_genau_lane(source):
                genau = lanes.genau_delivery_dir()
                return None if genau is None else genau.joinpath(*rest)
        return kino_folder.where_it_went(video, self.root, self.kino)


def move_into_the_lane_folders() -> MovedOut:
    library = _Library.configured()
    if not library.outbox.is_dir():
        return MovedOut()
    log.info("=== Moving what the retired %s holds into Kino's and Genau's folders ===", library.outbox)
    remove_partial_files(library.outbox, logger=log)
    inside = library.outbox.relative_to(library.videos)
    videos = _move_everything_under(library, library.videos, library.outbox)
    for tree in library.mirrors:
        _move_everything_under(library, tree, tree / inside)
    log.info("Moved out of the retired outbox: %d, left there: %d", videos.moved, videos.failed)
    return videos


def _move_everything_under(library: _Library, tree: Path, retired: Path) -> MovedOut:
    if not retired.is_dir():
        return MovedOut()
    moved = failed = 0
    for held in sorted(path for path in retired.rglob("*") if path.is_file()):
        went = library.where_it_went(library.videos / held.relative_to(tree))
        destination = None if went is None else tree / went.relative_to(library.videos)
        if _move(held, destination):
            moved += 1
        else:
            failed += 1
    remove_empty_dirs(retired)
    if retired.is_dir() and not any(retired.iterdir()):
        retired.rmdir()
    return MovedOut(moved, failed)


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
