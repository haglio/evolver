"""Delete every condemned video in the piles this family keeps, and its source.

Two piles: ``2_outbox/kinda_weird``, where a viewer's "mark as weird" and the
backfill's discard both put an outbox video, and the one beside Genau's clips
folder, where Genau puts a clip a session condemns. A condemned video takes its
``1_sorted`` source, its metadata sidecar and both versions' funscripts with it.
"""
from __future__ import annotations

import glob
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
from util import lanes, script_library
from util.alert import show_error
from util.media_files import is_finalized_video_file
from util.variants import UPSCALE_SUFFIX
from util.weird_piles import WeirdPile, weird_piles

log = logging.getLogger(__name__)


@dataclass
class PurgeWeirdResult:
    deleted_weird: int = 0
    deleted_sorted: int = 0
    deleted_metadata: int = 0
    deleted_scripts: int = 0
    missing_sorted: list[str] = field(default_factory=list)

    def __add__(self, other: PurgeWeirdResult) -> PurgeWeirdResult:
        return PurgeWeirdResult(
            deleted_weird=self.deleted_weird + other.deleted_weird,
            deleted_sorted=self.deleted_sorted + other.deleted_sorted,
            deleted_metadata=self.deleted_metadata + other.deleted_metadata,
            deleted_scripts=self.deleted_scripts + other.deleted_scripts,
            missing_sorted=self.missing_sorted + other.missing_sorted)


def run() -> PurgeWeirdResult:
    result = sum((_purge_pile(pile) for pile in weird_piles()), PurgeWeirdResult())

    if result.missing_sorted:
        _report_missing_sources(result.missing_sorted)

    log.info(
        "Purge done.  Deleted weird: %d, deleted sorted: %d, deleted metadata: %d, "
        "deleted funscripts: %d, missing sources: %d",
        result.deleted_weird, result.deleted_sorted, result.deleted_metadata,
        result.deleted_scripts, len(result.missing_sorted),
    )
    return result


def _purge_pile(pile: WeirdPile) -> PurgeWeirdResult:
    """What emptying *pile* deleted, and what source it could not find.

    A stage result rather than a record of its own: every field of one is a
    per-pile fact, and run() is the sum over the piles.
    """
    if not pile.directory.is_dir():
        return PurgeWeirdResult()

    weird_files = [
        p for p in pile.directory.iterdir()
        if is_finalized_video_file(p)
    ]
    if not weird_files:
        return PurgeWeirdResult()

    log.info("=== Stage: purge weird ===")
    log.info("WEIRD:  %s", pile.directory)
    log.info("Found %d file(s) to purge", len(weird_files))

    purged = PurgeWeirdResult()
    for weird_file in sorted(weird_files):
        src_name = _source_name(weird_file)
        # By name, not by pattern: a `[`, `*` or `?` in a file name is a
        # character of the name, and handed to rglob raw it matched nothing.
        matches = list(pile.sorted_dir.rglob(glob.escape(src_name)))
        matches = [p for p in matches if p.is_file()]

        if not matches:
            if pile.report_missing_sources:
                log.warning("No source found in 1_sorted for: %s  (expected: %s)",
                            weird_file.name, src_name)
                purged.missing_sorted.append(weird_file.name)
        else:
            for match in matches:
                match.unlink()
                purged.deleted_sorted += 1
                log.info("Deleted source: %s", match)
                purged.deleted_scripts += _delete_scripts(match, lanes.upscale_filed_for(match))

        for json_file in config.METADATA_DIR.rglob(glob.escape(weird_file.stem + ".json")):
            json_file.unlink()
            purged.deleted_metadata += 1
            log.info("Deleted metadata: %s", json_file)

        weird_file.unlink()
        purged.deleted_weird += 1
        log.info("Deleted weird:  %s", weird_file.name)
        purged.deleted_scripts += _delete_scripts(weird_file)

    return purged


def _delete_scripts(*videos: Path | None) -> int:
    """Delete the funscript each of *videos* has, mark and all; how many there
    were. A condemned upscale's stays where the upscale was filed until the
    scripts stage next runs, so its source's filed upscale is one of them."""
    held = script_library.scripts_held_for(*videos)
    for script in held:
        script_library.delete_script(script)
        log.info("Deleted funscript: %s", script)
    return len(held)


def source_stem(stem: str) -> str:
    """Strip known processing suffixes from an outbox file stem.

    Examples:
        'abc_topaz'         -> 'abc'
        'abc_topaz_cfr'     -> 'abc'
        'abc_apo8_gcg5_topaz' -> 'abc_apo8_gcg5'
        'abc_topaz_extra'   -> 'abc'
        'abc_apo8_gcg5'     -> 'abc'
        'abc_apo8_gcg5_x'   -> 'abc'
    """
    stripped_topaz = re.sub(rf"{re.escape(UPSCALE_SUFFIX)}(?:_.*)?$", "", stem)
    if stripped_topaz != stem:
        return stripped_topaz
    return re.sub(r"_apo8_gcg5(?:_.*)?$", "", stem)


def _source_name(outbox_file: Path) -> str:
    """Return the expected source filename for an outbox file."""
    return source_stem(outbox_file.stem) + outbox_file.suffix


def _report_missing_sources(missing: list[str]) -> None:
    lines = "\n".join(missing[:30])
    ellipsis = "\n..." if len(missing) > 30 else ""
    msg = (
        f"Evolver found {len(missing)} file(s) in kinda_weird with no corresponding "
        f"source in 1_sorted. The kinda_weird files were removed, but the matching "
        f"source cleanup could not be completed.\n\n"
        f"Check the log for full details:\n{config.LOG_FILE}\n\n"
        f"Affected files:\n{lines}{ellipsis}"
    )
    show_error("Evolver - Missing Sources", msg)
