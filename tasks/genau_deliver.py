"""Deliver upscaled Genau clips to the folder Genau plays from.

The last step of the Genau lane, which ``config.GENAU_SOURCE`` describes: once
the upscale exists, move it into ``videos/genau/clips/`` and retire the
``1_sorted`` copy it was made from. A loop goes through the Topaz stage like
any other AI video rather than being copied straight across, because one fresh
out of the graph is visibly softer than the clips already in that folder, which
came from upscaled library video.

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
from dataclasses import dataclass
from pathlib import Path

import config
from util import sidecar, video_type
from util.media_files import child_dirs, library_videos, remove_empty_dirs, unique_path
from util.sidecar import sidecar_path
from util.variants import is_upscaled_stem, sorted_stem_of

log = logging.getLogger(__name__)


@dataclass
class GenauDeliverResult:
    delivered: int = 0
    failed: int = 0


def _upscaled_genau_clips(root: Path, genau_source: str):
    """Every finished Genau upscale waiting in the outbox, whatever its orientation.

    The upscale stage files its output under ``<orient>/<source>/``, so the lane's
    clips are spread across the orientation folders rather than gathered in one.
    """
    for orient_dir in child_dirs(root):
        source_dir = orient_dir / genau_source
        if source_dir.is_dir():
            yield from sorted(library_videos(source_dir))


def _sorted_original(upscaled: Path, genau_sorted_dir: Path) -> Path | None:
    """The ``1_sorted`` video ``upscaled`` was made from, if it is still there.

    The upscale stage names its output ``<sorted stem>_topaz`` under the same
    ``<orient>/<source>`` pair, so the source path is recoverable from the output
    path alone — no bookkeeping to keep in step.
    """
    if not is_upscaled_stem(upscaled.stem):
        return None
    orient = upscaled.parent.parent.name
    for candidate in (genau_sorted_dir / orient).glob(
        f"{sorted_stem_of(upscaled.stem)}.*"
    ):
        if candidate.suffix.lower() in config.VIDEO_EXTENSIONS:
            return candidate
    return None


def _deliver(upscaled: Path, clips_dir: Path) -> Path:
    """Move one finished upscale into Genau's clips folder; return where it landed."""
    clips_dir.mkdir(parents=True, exist_ok=True)
    # Genau's folder is flat and holds clips carved by hand as well as
    # generated ones, so a name can genuinely already be taken and
    # delivering must never overwrite a clip that is already being played.
    destination = unique_path(clips_dir / upscaled.name)
    upscaled.replace(destination)
    return destination


def _move_sidecar(upscaled: Path, destination: Path) -> None:
    """Re-file the clip's metadata under where it now lives, saying what it is.

    The record travels with the clip rather than dying at the door: what a loop
    was generated from is worth as much in Genau's folder as it was in the
    outbox, and the kind Genau's clips *are* (:mod:`util.video_type`) has to be
    written down somewhere for the apps that ask.  A clip delivered with no
    record at all still gets one, holding that one answer.

    Neither half is a reason to abandon a delivery that has already happened:
    ``sidecar_path`` raises for a video under neither library root, and a clip
    that somehow sits outside them simply has nowhere to keep a record, while a
    metadata tree that cannot be written costs the generation record but not the
    kind — ``tasks.video_types`` finds the delivered clip with none and writes
    one on its next run.
    """
    try:
        was, now = sidecar.sidecar_path(upscaled), sidecar.sidecar_path(destination)
        sidecar.write(now, video_type.stamped(sidecar.read(was), video_type.GENAU_CLIP))
        was.unlink(missing_ok=True)
    except (ValueError, OSError):
        log.warning("Could not re-file the metadata for %s", upscaled.name, exc_info=True)


def _retire_source(upscaled: Path, genau_sorted_dir: Path) -> None:
    """Remove the ``1_sorted`` copy the delivered clip was made from.

    See the module docstring for why this is not optional.
    """
    original = _sorted_original(upscaled, genau_sorted_dir)
    if original is not None:
        original.unlink(missing_ok=True)
        remove_empty_dirs(genau_sorted_dir)


def run(
    *,
    outbox_dir: Path | None = None,
    sorted_dir: Path | None = None,
    genau_source: str | None = None,
    genau_clips_dir: Path | None = None,
) -> GenauDeliverResult:
    """Move every finished Genau upscale into Genau's folder, retiring its source.

    The four places the lane spans are arguments, resolved here rather than in
    the signature: a default is evaluated at import, which would freeze the
    value past ``override_config``. ``genau_source`` is the overlay's
    ``genau_source`` folder name, which origenerator reads from its own overlay
    under the same key; a parameter changes where the value can come from, not
    what it is called.
    """
    outbox_dir = config.OUT_UPSCALED_DIR if outbox_dir is None else outbox_dir
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    genau_source = config.GENAU_SOURCE if genau_source is None else genau_source
    genau_clips_dir = config.GENAU_CLIPS_DIR if genau_clips_dir is None else genau_clips_dir
    # The lane's own corner of 1_sorted. Composed once so the two helpers that
    # need it take one path rather than two halves they could pair differently.
    genau_sorted_dir = sorted_dir / genau_source

    result = GenauDeliverResult()
    log.info("=== Genau lane: 2_outbox -> %s ===", genau_clips_dir)

    for upscaled in _upscaled_genau_clips(outbox_dir, genau_source):
        try:
            destination = _deliver(upscaled, genau_clips_dir)
            _move_sidecar(upscaled, destination)
            _retire_source(upscaled, genau_sorted_dir)
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

    log.info("Genau lane done. Delivered: %d, Failed: %d", result.delivered, result.failed)
    return result
