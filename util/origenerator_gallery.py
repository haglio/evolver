from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from fractions import Fraction
from pathlib import Path

from app_support import gallery_rows
from app_support.gallery_rows import is_video_name, output_names
from app_support.video_names import generation_stem

import config

PUBLISHED = "origenerator_gallery_contract.json"


def generated_fps(checkout: Path) -> Fraction | None:
    try:
        published = json.loads((checkout / PUBLISHED).read_text(encoding="utf-8"))
        rate = Fraction(str(published["generated_fps"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rate if rate > 0 else None


def rows(columns: Iterable[str], *, optional: Iterable[str] = (), db_path=None) -> list[dict]:
    return gallery_rows.rows(columns, optional=optional,
                             db_path=config.ORIGENERATOR_DB_PATH if db_path is None else db_path)


REMADE_AT = "remade_at"
EVOLVER_UPSCALE = "evolver_upscale"
UPSCALE_PROVENANCE = "upscale_provenance"
LIBRARY_ID = "library_id"


def stems_made_again() -> set[str]:
    try:
        made = rows(("output_files",), optional=(REMADE_AT,))
    except FileNotFoundError:
        return set()
    return {generation_stem(stem) for stem in video_stems(made, lambda row: row.get(REMADE_AT))}


def video_stems(made: Iterable[dict], where: Callable[[dict], object]) -> set[str]:
    return {Path(name).stem for row in made if where(row)
            for name in output_names(row) if is_video_name(name)}


def the_one_version_in(folder: Path, name: str) -> Path | None:
    made_from = generation_stem(Path(name).stem)
    versions = [video for video in folder.iterdir()
                if video.is_file() and is_video_name(video.name)
                and generation_stem(video.stem) == made_from] if folder.is_dir() else []
    return versions[0] if len(versions) == 1 else None
