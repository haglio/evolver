"""The two ways this app reads one of its small JSON files.

The difference is what a file it cannot read means. A file this app writes for
itself reads as empty when it is absent or torn -- a missing one is the
ordinary first-run case, and a half-written one is something a pipeline stage
carries on past. A file another app owns is the opposite: a stage that rewrites
one must stop on a file it cannot read rather than treat it as empty and write
a new one over the top.

Writing them is not here. Landing a whole file is the same problem in every
repo of this family and is solved once, in
:func:`app_support.file_channel.write_whole`; four places here had rolled their
own tmp-then-replace, and the one format three apps write at the same time was
the one that had not.
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
