"""Reading and writing the app's small JSON files, and doing it atomically.

Four places wrote one of these by hand and three of them rolled the same
tmp-then-replace dance; the fourth -- the sidecar tree -- did not, and it is
the one file format three apps write concurrently, so it was the one that could
be read half-written.

What is shared here is the *durability*, not the formatting: how a payload is
serialized differs on purpose (the sidecars are indented two and newline
terminated, a funscript is minified, Chrome's bookmarks file is indented three)
and each caller keeps saying its own, byte for byte.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_dict(path: Path) -> dict:
    """*path*'s payload as a mapping — empty when it is absent or unreadable.

    The tolerant reader, for the files the app writes for itself: a missing one
    is the ordinary first-run case, and a half-written one is a thing to carry
    on past rather than a crash in a pipeline stage.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_dict_strict(path: Path) -> dict:
    """*path*'s payload, letting a missing or malformed file raise.

    For files another app owns: a stage that rewrites one of those must stop on
    a file it cannot read rather than treat it as empty and write a new one
    over the top.
    """
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_text(path: Path, text: str, *, newline: str | None = None) -> None:
    """Write *text* to *path* so a reader sees either the old file or the new one.

    Written beside the destination and renamed over it, because a rename within
    a directory is atomic and a write is not -- and these files are read by
    other processes while this one writes them.

    *newline* is the file's line-ending rule, passed through to open(): None
    translates to the platform's, "\\n" keeps it as written, "" leaves it to the
    caller (which is what the csv module requires). Each caller passes what its
    format has always used.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    temp_path.replace(path)
