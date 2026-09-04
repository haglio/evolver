"""Fun Time's favorites CSV: its rows, and the local path each one links to.

Two stages read this file — one repoints favorites at videos that moved, the
other drops the ones that are really gone — so the cell format lives here
rather than in whichever stage happened to need it first.

A ``local_file`` cell is a spreadsheet hyperlink, ``=HYPERLINK("<url>";"<label>")``,
whose URL is a ``file:///`` form with forward slashes and whose label is the same
path in Windows form. Repointing a favorite has to rewrite both halves.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from util.json_store import atomic_write_text

_HYPERLINK_RE = re.compile(r'^=HYPERLINK\("([^"]+)"[;,]"([^"]*)"\)\s*$', re.IGNORECASE)
_HYPERLINK_URL_RE = re.compile(r'^=HYPERLINK\("([^"]+)"[;,]', re.IGNORECASE)


LOCAL_COLUMN = "local_file"
WEB_COLUMN = "web_url"
HEADER = (LOCAL_COLUMN, WEB_COLUMN)


def file_column_name(fieldnames: list[str]) -> str | None:
    """Whichever column holds the local path, tolerating a BOM on the header."""
    normalized = {name.lstrip("﻿"): name for name in fieldnames}
    for candidate in ("file", "local_file"):
        match = normalized.get(candidate)
        if match is not None:
            return match
    return None


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    # newline="" all the way through, which is what the csv module requires:
    # it writes its own \r\n terminators and must not have them translated.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue(), newline="")


def local_path(value: str, base_dir: Path) -> Path | None:
    """The path a cell points at, or None when it is not a filesystem reference."""
    candidate = _hyperlink_target(value)
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path.lstrip("/")))
    if not _looks_like_a_path(candidate):
        return None

    path = Path(candidate)
    return path if path.is_absolute() else base_dir / path


def with_local_path(value: str, new_path: Path) -> str:
    """The same cell, pointing at *new_path* — hyperlink URL and label alike."""
    if _HYPERLINK_RE.match(value) is None:
        return str(new_path)
    return local_cell(new_path)


def local_cell(video: Path) -> str:
    """The ``local_file`` cell exactly as Fun Time writes it, which is the text
    Fun Time later matches to find, skip or remove the row."""
    url = "file:///" + str(video).replace("\\", "/").replace(" ", "%20")
    return f'=HYPERLINK("{url}";"{video}")'


def favorite_videos(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    fieldnames, rows = read_rows(path)
    column = file_column_name(fieldnames)
    if column is None:
        return []
    found = (local_path((row.get(column) or "").strip(), path.parent) for row in rows)
    return [video for video in found if video is not None]


def add_favorite(path: Path, video: Path) -> bool:
    """Append *video* as a favorite unless it is one already; True when a row went in."""
    if _lists(favorite_videos(path), video):
        return False
    fieldnames, rows = read_rows(path) if path.is_file() else (list(HEADER), [])
    column = file_column_name(fieldnames) or LOCAL_COLUMN
    rows.append({column: local_cell(video)})
    write_rows(path, fieldnames, rows)
    return True


def remove_favorite(path: Path, video: Path) -> bool:
    """Drop *video*'s row; True when there was one."""
    if not path.is_file():
        return False
    fieldnames, rows = read_rows(path)
    column = file_column_name(fieldnames)
    if column is None:
        return False
    kept = [
        row for row in rows
        if not _same_video(local_path((row.get(column) or "").strip(), path.parent), video)
    ]
    if len(kept) == len(rows):
        return False
    write_rows(path, fieldnames, kept)
    return True


def _lists(videos: list[Path], video: Path) -> bool:
    return any(_same_video(listed, video) for listed in videos)


def _same_video(listed: Path | None, video: Path) -> bool:
    return listed is not None and str(listed).lower() == str(video).lower()


def _hyperlink_target(value: str) -> str:
    match = _HYPERLINK_URL_RE.match(value)
    return match.group(1) if match else value


def _looks_like_a_path(candidate: str) -> bool:
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return True
    if candidate.startswith(("\\\\", "/", "./", "../")):
        return True
    return "\\" in candidate or "/" in candidate
