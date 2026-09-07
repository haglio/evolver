"""The piles a condemned video waits in, and where its source is.

Two directories hold videos on their way out of the library: the outbox's
``kinda_weird``, where a viewer's "mark as weird" and the backfill's discard
both put an outbox video, and the one beside Genau's clips folder, where Genau
puts a clip a session condemns. ``tasks.purge_weird`` empties both; anything
else that walks the library wants to know only that a file sitting in one is
about to go, so that it does not point something at it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class WeirdPile:
    """A pile of condemned videos, and the tree their sources are looked for in."""

    directory: Path
    sorted_dir: Path
    report_missing_sources: bool


def weird_piles() -> tuple[WeirdPile, ...]:
    """Both piles, each with the corner of ``1_sorted`` its files came from.

    The outbox pile takes files from every source folder, so the whole of
    ``1_sorted`` answers for it. Genau's pile takes only what the Genau lane
    delivered, and the lane files its sorted copies under its own source folder
    (``tasks.genau_deliver``) -- a video elsewhere under ``1_sorted`` that
    merely shares a stem with one of them belongs to a different lane.

    Only the outbox pile reports a source it cannot find. An outbox file still
    has its ``1_sorted`` copy beside it by construction, so a missing one is an
    orphan worth a dialog; the lane retires a loop's copy the moment it delivers
    the clip, so a condemned loop has no source to find and the same dialog
    would pop for every clip Genau condemns.
    """
    sorted_dir = config.SORTED_DIR
    return (
        WeirdPile(config.WEIRD_DIR, sorted_dir, report_missing_sources=True),
        WeirdPile(config.GENAU_WEIRD_DIR, sorted_dir / config.GENAU_SOURCE,
                  report_missing_sources=False),
    )
