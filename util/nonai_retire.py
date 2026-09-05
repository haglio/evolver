"""Moving a superseded non-AI original out of the way, once its upscale exists.

Three things happen at promotion and they are easy to conflate: the upscale is
handed what the original's sidecar says about the footage they share, the
original leaves its triage folder, and its sidecar and funscript go wherever it
went.  Getting the last two wrong is not a wrong number on a screen -- it is a
video in the wrong place, an orphaned sidecar the grouping stage prunes, or a
funscript the scripts sync then fails the whole run trying to relocate.  So
they live here, together, away from the encode supervision that calls them.

Where an original goes is the caller's to say: ``archive_root`` names an
archive outside the library, or is None for the bucket's own ``2*`` folder.
It is a required argument rather than a defaulted one because None is a real
answer here -- the public checkout's -- and a default that meant "ask config"
could not be told apart from it.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import config
from util import funscript, sidecar
from util.nonai_library import bucket_of, stage_dirs

log = logging.getLogger(__name__)

# The one part of a sidecar that describes the FILE rather than the footage in
# it: which family it belongs to and whether it is a processed variant.  An
# upscale's is its own, and the grouping stage stamps it on the same pass.
_FILE_SCOPED_SIDECAR_KEYS = frozenset({"version"})


def carry_metadata(source: Path, out: Path) -> bool:
    """Give *out* what *source*'s sidecar says about the footage they share.

    An upscale IS its original's footage, so the ``clip`` object naming which
    compilation the video was carved out of, and the act recorded on it,
    describe the upscale exactly as well.  They lived only on the original,
    though, and retirement takes its sidecar out of the library — so unless the
    upscale is handed its own copy first, promoting it is what loses them.

    Nothing downstream puts them back.  The grouping stage would copy a ``clip``
    across from an in-library original, but it runs later in the same pass and
    by then there is none.  So without this the upscale reaches the library with
    nothing to say it was ever a cut.

    Funscripts are deliberately not carried: :mod:`tasks.scripts_sync` already
    copies an original's script onto its processed variants, and a second thing
    writing scripts is a second thing to disagree with it.
    """
    payload = sidecar.read(_sidecar_beside_or_mirrored(source))
    carried = {
        key: value for key, value in payload.items()
        if key not in _FILE_SCOPED_SIDECAR_KEYS
    }
    if not carried:
        return False
    destination = _sidecar_beside_or_mirrored(out)
    existing = sidecar.read(destination)
    merged = {**existing, **carried}
    if merged == existing:
        return False
    sidecar.write(destination, merged)
    log.info("Carried metadata onto upscale: %s -> %s", source.name, out.name)
    return True


def retire_original(source: Path, *, archive_root: Path | None) -> None:
    """Move the superseded original out of the way, now that its upscale exists.

    Into the bucket's ``2*`` folder, as the user does by hand — or, when
    *archive_root* names an archive, out of the library altogether, because
    that folder is on the drive the encodes fill.
    """
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
    _move_mirrored_files(source, dest)
    log.info("Retired original: %s -> %s", source, dest)


def _sidecar_beside_or_mirrored(video: Path) -> Path:
    """Where *video*'s sidecar lives: mirrored under ``METADATA_DIR``, or beside it.

    The metadata tree mirrors the library and nothing else, so a retired original
    that has left the library keeps its own copy next to the video instead (see
    :func:`_archive_original`).  Asking the mirror where that is computes a path
    under a tree the video is not in, which is the ``ValueError`` here — the
    archive is the only thing outside the library this stage ever reads.
    """
    try:
        return sidecar.sidecar_path(video)
    except ValueError:
        return video.with_suffix(".json")


def _archive_original(source: Path, archive_root: Path) -> None:
    """Move *source* out of the library, under the archive at its library path.

    Its sidecar and funscript come along and sit beside it rather than in the
    mirrored trees, which only cover the library: an archived video is a cold
    copy that has to describe itself. Leaving the funscript behind is the worse
    half — it still matches the video by name, so the scripts sync would try to
    relocate it onto a destination the clip-scripts stage has already written,
    and fail the run on a collision nothing can resolve.

    The library root stays ambient rather than joining *archive_root* as a
    parameter: :func:`util.nonai_library.bucket_of` reads it too and cannot be
    told otherwise, and two spellings of one root that must agree is how a
    retire ends up computing a destination under a tree the video is not in.
    """
    dest = archive_root / source.relative_to(config.NON_AI_DIR)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for mirrored_path, suffix in (
        (sidecar.sidecar_path, ".json"),
        (funscript.script_path_for_video, config.FUNSCRIPT_EXTENSION),
    ):
        src = mirrored_path(source)
        if src.exists():
            shutil.move(str(src), str(dest.with_suffix(suffix)))
    shutil.move(str(source), str(dest))
    log.info("Archived original: %s -> %s", source, dest)


def _move_mirrored_files(source: Path, dest: Path) -> None:
    """Carry a retired original's sidecar and funscript to its new path.

    The metadata and script trees both mirror the video tree, so both of a
    moved video's files must move with it. A left-behind sidecar is orphaned
    and pruned, losing the ``clip`` family metadata Nau navigates by (the
    grouping stage re-stamps ``version`` on the next run; this keeps
    ``clip``/``video`` from vanishing). A left-behind funscript is worse than
    orphaned: the scripts sync would relocate it, but the clip-scripts stage
    runs first and writes the clip a fresh script at the new path, so the sync
    finds its destination taken and fails the run on an unresolvable collision.
    """
    for mirrored_path in (sidecar.sidecar_path, funscript.script_path_for_video):
        src = mirrored_path(source)
        if not src.exists():
            continue
        dst = mirrored_path(dest)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
