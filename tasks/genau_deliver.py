from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import upscale
from util import genau_flicks, lanes
from util.media_files import child_dirs, library_videos, remove_empty_dirs
from util.stage_result import StageResult
from util.versions import is_upscaled_stem, sorted_stem_of

log = logging.getLogger(__name__)


@dataclass
class GenauDeliverResult(StageResult):
    delivered: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed


def _fresh_upscales(genau_sorted_dir: Path):
    for folder in (lanes.genau_delivery_dir(), lanes.genaumacher_flicks_dir()):
        for flick in sorted(library_videos(folder)) if folder is not None and folder.is_dir() else ():
            original = _sorted_original(flick, genau_sorted_dir)
            if original is not None and not upscale.awaits_its_upscale(
                    original, genau_sorted_dir.name, original.parent.name):
                yield flick, original
            elif (beside := _original_beside(flick)) is not None:
                yield flick, beside


def _sorted_original(upscaled: Path, genau_sorted_dir: Path) -> Path | None:
    if not is_upscaled_stem(upscaled.stem):
        return None
    for orient_dir in child_dirs(genau_sorted_dir):
        for candidate in orient_dir.glob(f"{glob.escape(sorted_stem_of(upscaled.stem))}.*"):
            if candidate.suffix.lower() in config.VIDEO_EXTENSIONS:
                return candidate
    return None


def _original_beside(upscaled: Path) -> Path | None:
    if not is_upscaled_stem(upscaled.stem):
        return None
    original = upscaled.with_stem(sorted_stem_of(upscaled.stem))
    return original if original.is_file() else None


def _retire_the_sorted_copy(flick: Path, original: Path) -> bool:
    genau_flicks.save_its_sound(flick)
    try:
        # ComfyUI's output folder and Origenerator's gallery still hold the flick.
        original.unlink()
    except OSError:
        log.warning("Could not retire %s; leaving it for the next run",
                    original.name, exc_info=True)
        return False
    return True


def run() -> GenauDeliverResult:
    delivery_dir = lanes.genau_delivery_dir()
    genau_sorted_dir = config.SORTED_DIR / config.GENAU_SOURCE

    result = GenauDeliverResult()
    if delivery_dir is None:
        log.warning("=== Genau lane: no folder is laid out the way Genau's folder is; nothing delivered ===")
        return result
    log.info("=== Genau lane: finishing the upscales in %s ===", delivery_dir)

    for flick, original in _fresh_upscales(genau_sorted_dir):
        retired = (genau_flicks.take_the_place_of(original, flick) if original.parent == flick.parent
                   else _retire_the_sorted_copy(flick, original))
        if not retired:
            result.failed += 1
            continue
        log.info("DELIVER %s", flick)
        result.delivered += 1
    remove_empty_dirs(genau_sorted_dir)

    log.info("Genau lane done. Delivered: %d, Failed: %d", result.delivered, result.failed)
    return result
