"""Move videos from 0_inbox/<source>/ -> 1_sorted/<source>/<orientation>/"""
from __future__ import annotations

import filecmp
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import config
from util import lanes, orientation, origenerator_gallery, provenance, script_library, sidecar
from util.ffprobe import orientation_of
from util.media_files import child_dirs, library_videos, remove_empty_dirs
from util.sidecar import upscaled_video_path

log = logging.getLogger(__name__)


@dataclass
class SortResult:
    moved: int = 0
    deleted_collisions: int = 0
    made_again: int = 0
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

    sources = list(child_dirs(inbox_dir))
    made_again = cache(origenerator_gallery.stems_made_again)
    if not sources:
        log.info("No source directories found in inbox: %s", inbox_dir)

    for src_root in sources:
        source = src_root.name

        log.info("--- Sorting source: %s ---", source)

        for src in library_videos(src_root):
            orient = orientation_of(src)

            if orient not in orientation.SORTED:
                log.info("UNKNOWN (leaving in inbox): %s", src)
                result.skipped_unknown += 1
                continue

            rel = src.relative_to(src_root)
            dest = sorted_dir / source / orient / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            log.info("MOVE  [%s/%s] %s", source, orient, rel)
            if _a_remake_of(dest, src, source, made_again):
                _take_the_remake(src, dest, upscaled_video_path(source, orient, dest.stem))
                result.made_again += 1
                result.moved_files.append(dest)
            elif _move_unique(src, dest):
                result.moved += 1
                result.moved_files.append(dest)
            else:
                result.deleted_collisions += 1

        remove_empty_dirs(src_root)

    log.info(
        "Sort done. Moved: %d, Made again: %d, Deleted collisions: %d, Unknown skipped: %d",
        result.moved, result.made_again, result.deleted_collisions, result.skipped_unknown,
    )
    return result


def _a_remake_of(sorted_copy: Path, handed_over: Path, source: str,
                 made_again: Callable[[], set[str]]) -> bool:
    return (sorted_copy.exists() and lanes.sent_by_origenerator(source)
            and origenerator_gallery.origin_stem(handed_over.stem) in made_again()
            and not filecmp.cmp(handed_over, sorted_copy, shallow=False))


def _take_the_remake(src: Path, dest: Path, upscale: Path) -> None:
    """Put the video Origenerator made again in place of the copy sorted before,
    and have its upscale made again: its record forgets what made the upscale
    now under its name, and what made the video, which the Provenance stage
    looks up again."""
    log.info("MADE AGAIN (taking the place of its sorted copy): %s  ->  %s", src, dest)
    src.replace(dest)
    _carry_its_script(src, (dest, upscale))
    try:
        record = sidecar.sidecar_path(upscale)
    except ValueError:
        return
    sidecar.update(record, lambda current: provenance.recorded(
        provenance.without(current, provenance.GENERATION),
        provenance.UPSCALE, provenance.reconstructed(None)))


def _carry_its_script(handed_over: Path, copies: tuple[Path, ...]) -> None:
    """Give each copy the script handed over with *handed_over*, from wherever it
    waits: beside the video in the inbox, or where Stray Files moved it."""
    for script in (handed_over.with_suffix(config.FUNSCRIPT_EXTENSION),
                   script_library.script_path_for_video(handed_over)):
        if script.is_file():
            for copy in copies:
                copied_to = script_library.script_path_for_video(copy)
                script_library.copy_script(script, copied_to)
                script_library.mark_generated(copied_to)
            script_library.delete_script(script)
            return


def _move_unique(src: Path, dest: Path) -> bool:
    """Move src to dest. If dest exists, delete src instead. Returns True if moved."""
    if not dest.exists():
        src.rename(dest)
        return True
    log.info("COLLISION (deleting inbox file): %s  ->  %s", src, dest)
    src.unlink()
    return False
