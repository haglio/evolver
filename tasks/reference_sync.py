"""Stage: repoint the suite's saved video references at videos that moved.

Evolver relocates videos — sorting them, retiring an upscaled original, and the
library gets reorganized by hand between runs too. Every sibling app that saved
a video's path (Clipper's clip bounds, Fun Time's favorites and watch counts)
is left pointing at where the file used to be. This stage walks those stores
each run and follows the move.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from util import reference_stores, video_locator

log = logging.getLogger(__name__)


@dataclass
class ReferenceSyncResult:
    checked: int = 0
    relocated: int = 0
    unresolved: int = 0
    write_errors: int = 0

    @property
    def ok(self) -> bool:
        return not self.write_errors


def run() -> ReferenceSyncResult:
    result = ReferenceSyncResult()
    log.info("=== Stage: follow videos that moved ===")

    index = video_locator.build_index()
    for store in reference_stores.discover():
        _reconcile(store, index, result)

    log.info(
        "References done. Checked: %d, Relocated: %d, Unresolved: %d, Write errors: %d",
        result.checked,
        result.relocated,
        result.unresolved,
        result.write_errors,
    )
    return result


def _reconcile(
    store: reference_stores.ReferenceStore,
    index: dict[str, list[Path]],
    result: ReferenceSyncResult,
) -> None:
    references = store.read(store.path)
    result.checked += len(references)

    moves: dict[str, str] = {}
    for reference in references:
        was_at = Path(reference)
        if was_at.exists():
            continue
        now_at = video_locator.relocate(was_at, index) or _renamed(store, was_at)
        if now_at is None:
            result.unresolved += 1
            log.warning("UNRESOLVED %s reference (%s): %s", store.label, store.path.name, reference)
            continue
        moves[reference] = str(now_at)
        log.info("REPOINT %s  %s  ->  %s", store.label, reference, now_at)

    if not moves:
        return
    store.rewrite(store.path, moves)
    result.relocated += len(moves)


def _renamed(store: reference_stores.ReferenceStore, was_at: Path) -> Path | None:
    """Last resort: the video is still where it was, under a name it no longer has."""
    fingerprint = store.fingerprint(store.path)
    if fingerprint is None or not was_at.parent.is_dir():
        return None
    return video_locator.renamed_in_place(was_at, fingerprint)
