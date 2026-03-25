"""Stage 3: Delete all files from kinda_weird and their source files from 1_sorted."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import config
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class PurgeWeirdResult:
    deleted_weird: int = 0
    deleted_sorted: int = 0
    missing_sorted: List[str] = field(default_factory=list)


def run() -> PurgeWeirdResult:
    result = PurgeWeirdResult()
    roots = [root for root in config.active_weird_dirs() if root.is_dir()]
    if not roots:
        return result

    seen_header = False
    for weird_root in roots:
        weird_files = [
            p for p in weird_root.iterdir()
            if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS
        ]
        if not weird_files:
            continue

        if not seen_header:
            log.info("=== Stage 3: purge kinda_weird ===")
            seen_header = True
        log.info("WEIRD:  %s", weird_root)
        log.info("Found %d file(s) to purge", len(weird_files))

        for weird_file in sorted(weird_files):
            src_name = _source_name(weird_file)
            matches = list(config.SORTED_DIR.rglob(src_name))
            matches = [p for p in matches if p.is_file()]

            if not matches:
                log.warning("No source found in 1_sorted for: %s  (expected: %s)", weird_file.name, src_name)
                result.missing_sorted.append(weird_file.name)
            else:
                for match in matches:
                    match.unlink()
                    result.deleted_sorted += 1
                    log.info("Deleted source: %s", match)

            weird_file.unlink()
            result.deleted_weird += 1
            log.info("Deleted weird:  %s", weird_file.name)

    if not seen_header:
        return result

    if result.missing_sorted:
        _show_error_window(result.missing_sorted)

    log.info(
        "Stage 3 done.  Deleted weird: %d, deleted sorted: %d, missing sources: %d",
        result.deleted_weird, result.deleted_sorted, len(result.missing_sorted),
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    stripped_topaz = re.sub(r"_topaz(?:_.*)?$", "", stem)
    if stripped_topaz != stem:
        return stripped_topaz
    return re.sub(r"_apo8_gcg5(?:_.*)?$", "", stem)


def _source_name(outbox_file: Path) -> str:
    """Return the expected source filename for an outbox file."""
    return source_stem(outbox_file.stem) + outbox_file.suffix


def _show_error_window(missing: List[str]) -> None:
    lines = "\n".join(missing[:30])
    ellipsis = "\n..." if len(missing) > 30 else ""
    msg = (
        f"Evolver found {len(missing)} file(s) in kinda_weird with no corresponding "
        f"source in 1_sorted. The kinda_weird files were removed, but the matching "
        f"source cleanup could not be completed.\n\n"
        f"Check the log for full details:\n{config.LOG_FILE}\n\n"
        f"Affected files:\n{lines}{ellipsis}"
    )
    show_error_window("Evolver - Missing Sources", msg)
