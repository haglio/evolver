"""Move videos from 0_inbox/<source>/ -> 1_sorted/<source>/<orientation>/"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util.ffprobe import get_orientation
from util.media_files import iter_finalized_videos, remove_empty_dirs

log = logging.getLogger(__name__)


@dataclass
class SortResult:
    moved: int = 0
    deleted_collisions: int = 0
    skipped_unknown: int = 0
    moved_files: list[Path] = field(default_factory=list)


def run(*, inbox_dir: Path | None = None, sorted_dir: Path | None = None) -> SortResult:
    """Move every finalized inbox video into the sorted tree, by source and shape.

    The two folders are arguments so the signature says what the stage
    touches. They are resolved here rather than in the signature: a default
    evaluated at import would freeze whatever ``config`` held then, and the
    suite redirects those paths after this module has been imported.
    """
    inbox_dir = config.INBOX_DIR if inbox_dir is None else inbox_dir
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir

    result = SortResult()
    sorted_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage: 0_inbox -> 1_sorted (move) ===")
    log.info("INBOX:  %s", inbox_dir)
    log.info("SORTED: %s", sorted_dir)

    sources = list(_iter_source_dirs(inbox_dir))
    if not sources:
        log.info("No source directories found in inbox: %s", inbox_dir)

    for src_root in sources:
        source = src_root.name

        log.info("--- Sorting source: %s ---", source)

        for src in _iter_videos(src_root):
            orient = get_orientation(src)

            if orient not in ("landscape", "portrait"):
                log.info("UNKNOWN (leaving in inbox): %s", src)
                result.skipped_unknown += 1
                continue

            rel = src.relative_to(src_root)
            dest = sorted_dir / source / orient / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            log.info("MOVE  [%s/%s] %s", source, orient, rel)
            if _move_unique(src, dest):
                result.moved += 1
                result.moved_files.append(dest)
            else:
                result.deleted_collisions += 1

        remove_empty_dirs(src_root)

    log.info(
        "Sort done. Moved: %d, Deleted collisions: %d, Unknown skipped: %d",
        result.moved, result.deleted_collisions, result.skipped_unknown,
    )
    return result


def _move_unique(src: Path, dest: Path) -> bool:
    """Move src to dest. If dest exists, delete src instead. Returns True if moved."""
    if not dest.exists():
        src.rename(dest)
        return True
    log.info("COLLISION (deleting inbox file): %s  ->  %s", src, dest)
    src.unlink()
    return False


def _iter_videos(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def _iter_source_dirs(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir():
            yield p


