"""Origenerator's gallery database, read as a normal external source.

Origenerator is a sibling video-generation app that drops its finished videos in
``0_inbox/<source>/``. To Evolver it is a content source no different from
Provider: Evolver *pulls* what it needs and Origenerator never reaches back.
Where the Provider strategy scrapes a website, this one opens a database —
read-only, so a running Origenerator (which owns the file) is never at risk of a
write from here.

Two stages pull from it, and each reads its own columns: the metadata strategy
builds a clip's sidecar from the row that made it, and ``tasks.withdrawn``
deletes the clips whose send that gallery has taken back. The connection and the
read are here rather than in either of them, because there was one of each and
the second stage would have been a copy.

The upscale stage reads one thing from the document Origenerator publishes
beside the gallery: the rate its video models generate at, so that Topaz is
given only the frames a model made.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable
from fractions import Fraction
from pathlib import Path

import config
from util.media_files import strip_uniquifier
from util.variants import strip_processing_suffixes

log = logging.getLogger(__name__)

PUBLISHED = "origenerator_gallery_contract.json"


def generated_fps(checkout: Path) -> Fraction | None:
    try:
        published = json.loads((checkout / PUBLISHED).read_text(encoding="utf-8"))
        rate = Fraction(str(published["generated_fps"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rate if rate > 0 else None


def downtime_command(checkout: Path) -> tuple[str, ...] | None:
    try:
        published = json.loads((checkout / PUBLISHED).read_text(encoding="utf-8"))
        command = tuple(str(part) for part in published["downtime_command"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return command or None


def database(db_path=None) -> Path:
    """The gallery to read — *db_path*, else the configured one — which must exist.

    Raises ``FileNotFoundError`` when it is absent, which is the ordinary state
    of a machine with no Origenerator installed beside this one.
    """
    db_path = Path(db_path) if db_path is not None else config.ORIGENERATOR_DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"Origenerator database not found: {db_path}")
    return db_path


def rows(columns: Iterable[str], *, optional: Iterable[str] = (),
         db_path=None) -> list[dict]:
    """Every generation row, holding *columns* and whichever of *optional* exist.

    A column that a given Origenerator database may predate goes in *optional*:
    selecting one the table does not have raises, and the older gallery is the
    ordinary case for a column added recently. Absent, it is simply missing from
    every row, which each caller already has to handle for a row that holds NULL.
    """
    conn = _connect_ro(database(db_path))
    try:
        present = {column[1] for column in conn.execute("PRAGMA table_info(generations)")}
        selected = [*columns, *(name for name in optional if name in present)]
        cursor = conn.execute(f"SELECT {', '.join(selected)} FROM generations")
        return [dict(zip(selected, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()


#: The stamp Origenerator puts on a video it has made again in place, under the
#: name it was sent by. Optional: a gallery from before it has made nothing again.
REMADE_AT = "remade_at"


def stems_made_again() -> set[str]:
    """The stem of every video Origenerator has made again in place -- none when
    no gallery is beside this library."""
    try:
        made = rows(("output_files",), optional=(REMADE_AT,))
    except FileNotFoundError:
        return set()
    return video_stems(made, lambda row: row.get(REMADE_AT))


def video_stems(made: Iterable[dict], where: Callable[[dict], object]) -> set[str]:
    """The stem of every video the rows of *made* that *where* holds of produced.

    A stem rather than a name, because what arrived and what is here now differ
    by everything this library appends (:func:`origin_stem`).
    """
    return {Path(name).stem for row in made if where(row)
            for name in output_names(row) if is_video_name(name)}


def origin_stem(stem: str) -> str:
    """*stem* with everything this library appends taken back off.

    A clip arrives under the name Origenerator gave it, is uniquified if that
    name was taken, upscaled under a ``_topaz`` suffix and uniquified again if
    the delivered folder had it -- so the pair of reductions runs until neither
    one changes anything, rather than once each in an order that leaves what the
    other would have taken off still on the end.
    """
    while True:
        reduced = strip_processing_suffixes(strip_uniquifier(stem))
        if reduced == stem:
            return stem
        stem = reduced


def output_names(row: dict) -> list[str]:
    """The file names a generation row says it produced, or none if it says badly.

    A row is another app's data, so a column holding something other than the
    list of ``{"filename": ...}`` it usually holds costs that one row, not the run.
    """
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
    """A read-only connection, opened by URI so a wrong path fails loudly instead
    of creating an empty file."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)
