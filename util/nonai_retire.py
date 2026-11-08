from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app_support import video_ids

import config
from util import script_library, sidecar
from util.library_moves import MIRRORS, move_its_records
from util.nonai_library import bucket_of, stage_dirs

log = logging.getLogger(__name__)

_FILE_SCOPED_SIDECAR_KEYS = frozenset({"version", video_ids.ID_KEY})


def carry_metadata(source: Path, out: Path) -> bool:
    payload = sidecar.read(sidecar.sidecar_path(source))
    carried = {
        key: value for key, value in payload.items()
        if key not in _FILE_SCOPED_SIDECAR_KEYS
    }
    if not carried:
        return False

    def carry_them_over(existing: dict) -> dict | None:
        merged = {**existing, **carried}
        return merged if merged != existing else None

    if sidecar.update(sidecar.sidecar_path(out), carry_them_over) is None:
        return False
    log.info("Carried metadata onto upscale: %s -> %s", source.name, out.name)
    return True


def carry_funscript(source: Path, out: Path) -> None:
    script = script_library.script_path_for_video(source)
    destination = script_library.script_path_for_video(out)
    if script.is_file() and not destination.exists():
        script_library.copy_script(script, destination)
        log.info("Carried funscript onto upscale: %s -> %s", source.name, out.name)


def retire_original(source: Path, *, archive_root: Path | None) -> None:
    if archive_root is not None:
        _archive_original(source, archive_root)
        return
    bucket = bucket_of(source)
    retire_dirs = stage_dirs(bucket, digits=(2,)) if bucket else []
    if not retire_dirs:
        log.warning("No '2*' folder in %s; leaving the original at %s.", bucket, source)
        return
    dest = retire_dirs[0][1] / source.name
    if dest.exists():
        log.warning("Original collides with %s; leaving it at %s.", dest, source)
        return
    source.replace(dest)
    move_its_records(source, dest)
    log.info("Retired original: %s -> %s", source, dest)


def _archive_original(source: Path, archive_root: Path) -> None:
    dest = archive_root / source.relative_to(config.NON_AI_DIR)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for mirror in MIRRORS:
        src = mirror(source)
        if src.exists():
            shutil.move(str(src), str(dest.with_suffix(src.suffix)))
    script_library.drop_mark(script_library.script_path_for_video(source))
    shutil.move(str(source), str(dest))
    log.info("Archived original: %s -> %s", source, dest)
