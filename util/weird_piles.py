from __future__ import annotations

import re
from pathlib import Path

import config
from util.media_files import library_videos

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
