"""Deliver upscaled Genau clips to the folder Genau plays from.

Origenerator makes a Genau clip — one complete stroke, looping end to end — and
drops it in the inbox under its own source folder (``config.GENAU_SOURCE``,
which the content overlay names). From there it is an ordinary AI
video: sorted by orientation, then upscaled by the Topaz stage like everything
else, which is the whole reason it comes through here rather than being copied
straight to Genau. A loop fresh out of the graph is visibly softer than the clips
already in that folder, which came from upscaled library video.

This is the last step of that lane: once the upscale exists, move it into
``videos/genau/clips/`` and retire the ``1_sorted`` copy it was made from.

Both halves leave together, and that is not tidiness:

- The upscale stage decides what still needs doing by looking for the output
  beside the source (``upscale._already_processed``). Take the output away and
  leave the source, and every future run upscales that clip again, forever.
- The correspondence check (``check_correspondence``) requires each ``1_sorted``
  video to have a ``_topaz`` counterpart in the outbox, and pops a Windows error
  dialog when one doesn't. Removing one side alone is exactly that mismatch.

Nothing unique is lost with the sorted copy: it was itself a copy, and the clip
still sits in ComfyUI's output folder and in Origenerator's gallery.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util import sidecar, video_type
from util.media_files import iter_finalized_videos, remove_empty_dirs

log = logging.getLogger(__name__)


@dataclass
class GenauDeliverResult:
    delivered: int = 0
    failed: int = 0
    delivered_files: list[Path] = field(default_factory=list)


def _upscaled_genau_clips():
    """Every finished Genau upscale waiting in the outbox, whatever its orientation.

    The upscale stage files its output under ``<orient>/<source>/``, so the lane's
    clips are spread across the orientation folders rather than gathered in one.
    """
    root = config.OUT_UPSCALED_DIR
    if not root.is_dir():
        return
    for orient_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        source_dir = orient_dir / config.GENAU_SOURCE
        if source_dir.is_dir():
            yield from sorted(iter_finalized_videos(source_dir, config.VIDEO_EXTENSIONS))


def _sorted_original(upscaled: Path) -> Path | None:
    """The ``1_sorted`` video ``upscaled`` was made from, if it is still there.

    The upscale stage names its output ``<sorted stem>_topaz`` under the same
    ``<orient>/<source>`` pair, so the source path is recoverable from the output
    path alone — no bookkeeping to keep in step.
    """
    if not upscaled.stem.endswith("_topaz"):
        return None
    orient = upscaled.parent.parent.name
    for candidate in (config.SORTED_DIR / config.GENAU_SOURCE / orient).glob(
        f"{upscaled.stem[: -len('_topaz')]}.*"
    ):
        if candidate.suffix.lower() in config.VIDEO_EXTENSIONS:
            return candidate
    return None


def _unique_destination(path: Path) -> Path:
    """``path`` if the name is free, else the same name with a `` (2)``, ``(3)``…

    Genau's folder is flat and holds clips carved by hand as well as generated
    ones, so a name can genuinely already be taken; delivering must never quietly
    overwrite a clip that is already being played.
    """
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _deliver(upscaled: Path) -> Path:
    """Move one finished upscale into Genau's clips folder; return where it landed."""
    config.GENAU_CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(config.GENAU_CLIPS_DIR / upscaled.name)
    upscaled.replace(destination)
    return destination


def _move_sidecar(upscaled: Path, destination: Path) -> None:
    """Re-file the clip's metadata under where it now lives, saying what it is.

    The record travels with the clip rather than dying at the door: what a loop
    was generated from is worth as much in Genau's folder as it was in the
    outbox, and the kind Genau's clips *are* (:mod:`util.video_type`) has to be
    written down somewhere for the apps that ask.  A clip delivered with no
    record at all still gets one, holding that one answer.

    ``sidecar_path`` raises for a video under neither library root; a clip that
    somehow sits outside them simply has nowhere to keep a record, which is not
    a reason to abandon the delivery.
    """
    try:
        was, now = sidecar.sidecar_path(upscaled), sidecar.sidecar_path(destination)
    except ValueError:
        return
    sidecar.write(now, video_type.stamped(sidecar.read(was), video_type.GENAU_CLIP))
    was.unlink(missing_ok=True)


def _retire_source(upscaled: Path) -> None:
    """Remove the ``1_sorted`` copy the delivered clip was made from.

    See the module docstring for why this is not optional.
    """
    original = _sorted_original(upscaled)
    if original is not None:
        original.unlink(missing_ok=True)
        remove_empty_dirs(config.SORTED_DIR / config.GENAU_SOURCE)


def run() -> GenauDeliverResult:
    """Move every finished Genau upscale into Genau's folder, retiring its source."""
    result = GenauDeliverResult()
    log.info("=== Genau lane: 2_outbox -> %s ===", config.GENAU_CLIPS_DIR)

    for upscaled in _upscaled_genau_clips():
        try:
            destination = _deliver(upscaled)
            _move_sidecar(upscaled, destination)
            _retire_source(upscaled)
        except OSError:
            # A clip Genau is playing right now is locked on Windows. Leaving it
            # is right: it is still a valid outbox entry with its source beside
            # it, so nothing is inconsistent and the next run delivers it.
            log.warning("Could not deliver %s; leaving it for the next run",
                        upscaled.name, exc_info=True)
            result.failed += 1
            continue
        log.info("DELIVER %s -> %s", upscaled.name, destination)
        result.delivered += 1
        result.delivered_files.append(destination)

    log.info("Genau lane done. Delivered: %d, Failed: %d", result.delivered, result.failed)
    return result
