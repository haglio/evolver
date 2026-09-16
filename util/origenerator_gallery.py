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
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import config


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
        return [dict(zip(selected, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """A read-only connection, opened by URI so a wrong path fails loudly instead
    of creating an empty file."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)
