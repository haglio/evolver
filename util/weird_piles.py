from __future__ import annotations

import glob
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes, script_library
from util.media_files import library_videos, retry_while_in_use, strip_uniquifier
from util.sidecar import sidecar_folder, sidecar_path
from util.variants import sorted_stem_of

log = logging.getLogger(__name__)

_DUPLICATE = "__dup"
_DUPLICATE_NUMBER = re.compile(rf"{_DUPLICATE}\d+$")


def weird_pile_dirs() -> tuple[Path, Path]:
    return config.WEIRD_DIR, config.GENAU_WEIRD_DIR


def free_spot_in(pile: Path, name: str) -> Path:
    spot = pile / name
    number = 1
    while spot.exists():
        spot = pile / f"{Path(name).stem}{_DUPLICATE}{number}{Path(name).suffix}"
        number += 1
    return spot


def name_it_had(video: Path) -> str:
    return f"{_DUPLICATE_NUMBER.sub('', video.stem)}{video.suffix}"


def stems_marked_weird() -> set[str]:
    return {Path(name_it_had(video)).stem
            for pile in weird_pile_dirs() for video in library_videos(pile)}


@dataclass(frozen=True)
class MarkedWeird:
    video: Path
    restores_to: Path | None
    upscaled_from: Path | None = None


def marked_weird() -> list[MarkedWeird]:
    outbox_pile, genau_pile = weird_pile_dirs()
    sorted_copies = _sorted_copies_by_stem()
    return ([_out_of_the_outbox(video, sorted_copies)
             for video in sorted(library_videos(outbox_pile))]
            + [_out_of_genau(video, genau_pile, sorted_copies)
               for video in sorted(library_videos(genau_pile))])


def _sorted_copies_by_stem() -> dict[str, list[Path]]:
    by_stem = defaultdict(list)
    for copy in library_videos(config.SORTED_DIR):
        by_stem[copy.stem].append(copy)
    return by_stem


def _out_of_the_outbox(video: Path, sorted_copies: dict[str, list[Path]]) -> MarkedWeird:
    upscales = {spot: copy
                for copy in sorted_copies.get(sorted_stem_of(Path(name_it_had(video)).stem), [])
                if (spot := lanes.upscale_filed_for(copy)) is not None}
    restores_to = _the_one_vacant(list(upscales)) or _the_one_vacant(_recorded_spots(video))
    return MarkedWeird(video, restores_to, upscales.get(restores_to))


def _out_of_genau(video: Path, pile: Path, sorted_copies: dict[str, list[Path]]) -> MarkedWeird:
    lane = config.SORTED_DIR / config.GENAU_SOURCE
    left_in_the_lane = [copy
                        for copy in sorted_copies.get(sorted_stem_of(strip_uniquifier(video.stem)), [])
                        if copy.is_relative_to(lane)]
    return MarkedWeird(video, _the_one_vacant([config.GENAU_CLIPS_DIR / video.relative_to(pile)]),
                       left_in_the_lane[0] if len(left_in_the_lane) == 1 else None)


def _recorded_spots(video: Path) -> list[Path]:
    name = name_it_had(video)
    return [root / record.parent.relative_to(records) / name
            for root in (config.OUT_UPSCALED_DIR, config.NON_AI_DIR)
            if (records := sidecar_folder(root)) is not None
            for record in records.rglob(glob.escape(f"{Path(name).stem}.json"))]


def restore(marked: MarkedWeird) -> None:
    if marked.restores_to is None:
        raise ValueError(f"Nothing says where {marked.video.name} was marked weird from")
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


def delete_permanently(marked: MarkedWeird) -> None:
    own_record = sidecar_path(marked.restores_to) if marked.restores_to is not None else None
    for gone in (marked.upscaled_from, marked.video, own_record, _sound_only_it_plays(marked)):
        if gone is not None and gone.exists():
            retry_while_in_use(gone.unlink)
            log.info("Deleted permanently: %s", gone)
    for script in script_library.scripts_held_for(marked.video, marked.restores_to, marked.upscaled_from):
        script_library.delete_script(script)
        log.info("Deleted permanently: %s", script)


def _sound_only_it_plays(marked: MarkedWeird) -> Path | None:
    _, genau_pile = weird_pile_dirs()
    if not marked.video.is_relative_to(genau_pile):
        return None
    if any(video.stem == marked.video.stem and video != marked.video
           for video in library_videos(config.GENAU_CLIPS_DIR.parent)):
        return None
    return config.GENAU_AUDIO_DIR / f"{marked.video.stem}.mp3"


def _the_one_vacant(spots: list[Path]) -> Path | None:
    vacant = [spot for spot in spots if not spot.exists()]
    return vacant[0] if len(vacant) == 1 else None
