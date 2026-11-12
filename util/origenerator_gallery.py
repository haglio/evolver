from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable
from fractions import Fraction
from pathlib import Path

from app_support.video_names import generation_stem

import config

log = logging.getLogger(__name__)

PUBLISHED = "origenerator_gallery_contract.json"


def generated_fps(checkout: Path) -> Fraction | None:
    try:
        published = json.loads((checkout / PUBLISHED).read_text(encoding="utf-8"))
        rate = Fraction(str(published["generated_fps"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rate if rate > 0 else None


def database(db_path=None) -> Path:
    db_path = Path(db_path) if db_path is not None else config.ORIGENERATOR_DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"Origenerator database not found: {db_path}")
    return db_path


def rows(columns: Iterable[str], *, optional: Iterable[str] = (),
         db_path=None) -> list[dict]:
    conn = _connect_ro(database(db_path))
    try:
        present = {column[1] for column in conn.execute("PRAGMA table_info(generations)")}
        selected = [*columns, *(name for name in optional if name in present)]
        cursor = conn.execute(f"SELECT {', '.join(selected)} FROM generations")
        return [dict(zip(selected, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()


REMADE_AT = "remade_at"


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


def output_names(row: dict) -> list[str]:
    entries = output_entries(row)
    if entries is None:
        log.warning("Could not read what a generation produced: %r", row.get("output_files"))
        return []
    return [entry["filename"] for entry in entries]


def output_entries(row: dict) -> list[dict] | None:
    try:
        return [entry for entry in json.loads(row.get("output_files") or "[]")
                if entry.get("filename")]
    except (AttributeError, TypeError, ValueError):
        return None


def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in config.VIDEO_EXTENSIONS


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    # SQLite handed a plain path that does not exist makes an empty database
    # there; opened read-only by URI, a wrong path fails instead.
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)
