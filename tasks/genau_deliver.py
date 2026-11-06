from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import config
from util import lanes, origenerator_gallery, provenance, sidecar, video_kind
from util.ffprobe import has_sound
from util.media_files import (
    child_dirs,
    library_videos,
    remove_empty_dirs,
    take_its_place,
    unique_path,
)
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


def _upscaled_genau_flicks(root: Path, genau_source: str):
    for orient_dir in child_dirs(root):
        source_dir = orient_dir / genau_source
        if source_dir.is_dir():
            yield from sorted(library_videos(source_dir))


def _sorted_original(upscaled: Path, genau_sorted_dir: Path) -> Path | None:
    if not is_upscaled_stem(upscaled.stem):
        return None
    orient = upscaled.parent.parent.name
    for candidate in (genau_sorted_dir / orient).glob(
        f"{sorted_stem_of(upscaled.stem)}.*"
    ):
        if candidate.suffix.lower() in config.VIDEO_EXTENSIONS:
            return candidate
    return None


def _deliver(upscaled: Path, delivery_dir: Path, made_again: Callable[[], set[str]]) -> Path:
    delivery_dir.mkdir(parents=True, exist_ok=True)
    played = delivery_dir / upscaled.name
    if played.exists() and origenerator_gallery.origin_stem(upscaled.stem) in made_again():
        take_its_place(upscaled, played)
        return played
    destination = unique_path(played)
    upscaled.replace(destination)
    return destination


def _move_sidecar(upscaled: Path, destination: Path) -> None:
    try:
        was, now = sidecar.sidecar_path(upscaled), sidecar.sidecar_path(destination)
        sidecar.update(now, lambda delivered: video_kind.stamped(
            provenance.carried_forward(delivered, {**delivered, **sidecar.read(was)}),
            video_kind.GENAU_FLICK))
        was.unlink(missing_ok=True)
    except (ValueError, OSError):
        log.warning("Could not re-file the metadata for %s", upscaled.name, exc_info=True)


def _save_its_sound(flick: Path, audio_dir: Path) -> None:
    if not has_sound(flick):
        return
    try:
        save_as_mp3(flick, audio_dir / f"{flick.stem}.mp3")
    except (OSError, subprocess.CalledProcessError):
        log.warning("Could not save the sound of %s", flick.name, exc_info=True)


def _retire_source(upscaled: Path, genau_sorted_dir: Path) -> None:
    original = _sorted_original(upscaled, genau_sorted_dir)
    if original is not None:
        original.unlink(missing_ok=True)
        remove_empty_dirs(genau_sorted_dir)


def run(
    *,
    outbox_dir: Path | None = None,
    sorted_dir: Path | None = None,
    genau_source: str | None = None,
    delivery_dir: Path | None = None,
    genau_audio_dir: Path | None = None,
) -> GenauDeliverResult:
    outbox_dir = config.OUT_UPSCALED_DIR if outbox_dir is None else outbox_dir
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    genau_source = config.GENAU_SOURCE if genau_source is None else genau_source
    delivery_dir = lanes.genau_delivery_dir() if delivery_dir is None else delivery_dir
    genau_audio_dir = config.GENAU_AUDIO_DIR if genau_audio_dir is None else genau_audio_dir
    genau_sorted_dir = sorted_dir / genau_source

    result = GenauDeliverResult()
    made_again = cache(origenerator_gallery.stems_made_again)
    if delivery_dir is None:
        log.warning("=== Genau lane: no folder is laid out as Genau's flicks are; nothing delivered ===")
        return result
    log.info("=== Genau lane: 2_outbox -> %s ===", delivery_dir)

    for upscaled in _upscaled_genau_flicks(outbox_dir, genau_source):
        try:
            destination = _deliver(upscaled, delivery_dir, made_again)
            _move_sidecar(upscaled, destination)
            _save_its_sound(destination, genau_audio_dir)
            _retire_source(upscaled, genau_sorted_dir)
        except OSError:
            # Windows locks a flick Genau is playing.
            log.warning("Could not deliver %s; leaving it for the next run",
                        upscaled.name, exc_info=True)
            result.failed += 1
            continue
        log.info("DELIVER %s -> %s", upscaled.name, destination)
        result.delivered += 1

    log.info("Genau lane done. Delivered: %d, Failed: %d", result.delivered, result.failed)
    return result
