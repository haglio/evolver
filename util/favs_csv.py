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
    url = "file:///" + str(new_path).replace("\\", "/")
    return f'=HYPERLINK("{url}";"{new_path}")'


def _hyperlink_target(value: str) -> str:
    match = _HYPERLINK_URL_RE.match(value)
    return match.group(1) if match else value


def _looks_like_a_path(candidate: str) -> bool:
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return True
    if candidate.startswith(("\\\\", "/", "./", "../")):
        return True
    return "\\" in candidate or "/" in candidate
