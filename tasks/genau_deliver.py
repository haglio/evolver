from __future__ import annotations

import glob
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app_support.video_kind import GENAU_FLICK

import config
from tasks import upscale
from util import lanes, sidecar, video_kind
from util.ffprobe import has_sound
from util.media_files import child_dirs, library_videos, remove_empty_dirs
from util.sound import save_as_mp3
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


def _fresh_upscales(delivery_dir: Path, genau_sorted_dir: Path):
    for flick in sorted(library_videos(delivery_dir)):
        original = _sorted_original(flick, genau_sorted_dir)
        if original is not None and not upscale.awaits_its_upscale(
                original, genau_sorted_dir.name, original.parent.name):
            yield flick, original


def _sorted_original(upscaled: Path, genau_sorted_dir: Path) -> Path | None:
    if not is_upscaled_stem(upscaled.stem):
        return None
    for orient_dir in child_dirs(genau_sorted_dir):
        for candidate in orient_dir.glob(f"{glob.escape(sorted_stem_of(upscaled.stem))}.*"):
            if candidate.suffix.lower() in config.VIDEO_EXTENSIONS:
                return candidate
    return None


def _say_what_it_is(flick: Path) -> None:
    try:
        sidecar.update(sidecar.sidecar_path(flick),
                       lambda record: video_kind.stamped(record, GENAU_FLICK))
    except (ValueError, OSError):
        log.warning("Could not record what %s is", flick.name, exc_info=True)


def _save_its_sound(flick: Path, audio_dir: Path) -> None:
    if not has_sound(flick):
        return
    try:
        save_as_mp3(flick, audio_dir / f"{flick.stem}.mp3")
    except (OSError, subprocess.CalledProcessError):
        log.warning("Could not save the audio of %s", flick.name, exc_info=True)


def run() -> GenauDeliverResult:
    delivery_dir = lanes.genau_delivery_dir()
    genau_sorted_dir = config.SORTED_DIR / config.GENAU_SOURCE

    result = GenauDeliverResult()
    if delivery_dir is None:
        log.warning("=== Genau lane: no folder is laid out the way Genau's folder is; nothing delivered ===")
        return result
    log.info("=== Genau lane: finishing the upscales in %s ===", delivery_dir)

    for flick, original in _fresh_upscales(delivery_dir, genau_sorted_dir):
        _say_what_it_is(flick)
        _save_its_sound(flick, config.GENAU_AUDIO_DIR)
        try:
            # ComfyUI's output folder and Origenerator's gallery still hold the flick.
            original.unlink()
        except OSError:
            log.warning("Could not retire %s; leaving it for the next run",
                        original.name, exc_info=True)
            result.failed += 1
            continue
        log.info("DELIVER %s", flick)
        result.delivered += 1
    remove_empty_dirs(genau_sorted_dir)

    log.info("Genau lane done. Delivered: %d, Failed: %d", result.delivered, result.failed)
    return result
