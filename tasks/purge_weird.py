"""Delete every file in kinda_weird, and its source file in 1_sorted."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import glob

import config
from util.alert import show_error
from util.media_files import is_finalized_video_file
from util.variants import UPSCALE_SUFFIX

log = logging.getLogger(__name__)


@dataclass
class PurgeWeirdResult:
    deleted_weird: int = 0
    deleted_sorted: int = 0
    deleted_metadata: int = 0
    missing_sorted: list[str] = field(default_factory=list)


def run() -> PurgeWeirdResult:
    result = PurgeWeirdResult()
    weird_root = config.WEIRD_DIR
    if not weird_root.is_dir():
        return result

    weird_files = [
        p for p in weird_root.iterdir()
        if is_finalized_video_file(p, config.VIDEO_EXTENSIONS)
    ]
    if not weird_files:
        return result

    log.info("=== Stage: purge kinda_weird ===")
    log.info("WEIRD:  %s", weird_root)
    log.info("Found %d file(s) to purge", len(weird_files))

    for weird_file in sorted(weird_files):
        src_name = _source_name(weird_file)
        # By name, not by pattern: a `[`, `*` or `?` in a file name is a
        # character of the name, and handed to rglob raw it matched nothing.
        matches = list(config.SORTED_DIR.rglob(glob.escape(src_name)))
        matches = [p for p in matches if p.is_file()]

        if not matches:
            log.warning("No source found in 1_sorted for: %s  (expected: %s)", weird_file.name, src_name)
            result.missing_sorted.append(weird_file.name)
        else:
            for match in matches:
                match.unlink()
                result.deleted_sorted += 1
                log.info("Deleted source: %s", match)

        for json_file in config.METADATA_DIR.rglob(glob.escape(weird_file.stem + ".json")):
            json_file.unlink()
            result.deleted_metadata += 1
            log.info("Deleted metadata: %s", json_file)

        weird_file.unlink()
        result.deleted_weird += 1
        log.info("Deleted weird:  %s", weird_file.name)

    if result.missing_sorted:
        _report_missing_sources(result.missing_sorted)

    log.info(
        "Purge done.  Deleted weird: %d, deleted sorted: %d, deleted metadata: %d, missing sources: %d",
        result.deleted_weird, result.deleted_sorted, result.deleted_metadata, len(result.missing_sorted),
    )
    return result


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
