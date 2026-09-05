"""Example thumbnails for the backfill window's clickable tiles.

Each act tile shows a still from a clip that illustrates that act, so the grid reads
as a gallery you recognize at a glance rather than a wall of words. A thumbnail is one
extracted frame, cached under ``config.BACKFILL_THUMBNAIL_DIR`` and reused on every
later open, so the window only ever loads ready files — it never extracts on open.

A tile's example comes from one of two places, curated first:

* ``config.CURATED_EXAMPLES`` pins a specific clip to a tile by id. This is how the acts
  the library never tags in a camera-scoped form get a picture — a side gamma, a POV
  zeta — and how a clip mistagged (or tagged for a different act than it best shows)
  is still put to use.
* otherwise the first library clip whose ``video.action`` matches the tile, taken from
  a single scan. A compound tag like ``Pov Epsilon, Alpha`` counts as each of its
  comma-separated parts, so it can illustrate either tile.

The pure pieces take their effects as arguments or touch only the filesystem, so they
are tested without ffmpeg or Qt.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from backfill.queue import iter_library_videos
from backfill.vocabulary import scoped_grid
from util.ffprobe import duration_seconds
from util.sidecar import action_of, read, sidecar_path
from util.variants import sorted_stem_of

log = logging.getLogger(__name__)

_THUMBNAIL_HEIGHT = 96
# Sample the frame a little under halfway in: past a clip's title card or fade-in, and
# far enough that the act — and the anchor — is actually in frame, not just beginning.
_SAMPLE_FRACTION = 0.4

def _tile_actions() -> list[str]:
    """Every act a tile is built for, in grid order — the labels a thumbnail fills."""
    return [command.label for row in scoped_grid() for command in row]


def _scan_library() -> tuple[dict[str, Path], dict[str, Path]]:
    """One library pass, returning two lookups the examples are resolved through.

    ``by_action`` maps each action (and each part of a compound tag), lower-cased, to
    the first clip that carries it; ``by_id`` maps each clip's id — its stem without
    the ``_topaz`` suffix — to the clip, for the curated pins.
    """
    by_action: dict[str, Path] = {}
    by_id: dict[str, Path] = {}
    for _source, video in iter_library_videos():
        stem = video.stem
        clip_id = sorted_stem_of(stem)
        by_id.setdefault(clip_id, video)
        action = action_of(read(sidecar_path(video)))
        if action:
            for part in action.split(","):
                part = part.strip().lower()
                if part:
                    by_action.setdefault(part, video)
    return by_action, by_id


def example_clips() -> dict[str, Path]:
    """One example clip per tile that has one, as ``tile action -> clip``.

    A curated pin wins; otherwise the tile takes the first library clip whose action
    matches it. Tiles with neither are simply absent, and stay text-only.
    """
    by_action, by_id = _scan_library()
    examples: dict[str, Path] = {}
    for action in _tile_actions():
        clip = (by_id.get(config.CURATED_EXAMPLES.get(action, ""))
                or by_action.get(action.lower()))
        if clip is not None:
            examples[action] = clip
    return examples


def thumbnail_cache_path(action: str) -> Path:
    """Where *action*'s cached thumbnail lives — one stable file name per tile."""
    slug = re.sub(r"[^a-z0-9]+", "_", action.lower()).strip("_") or "unnamed"
    return config.BACKFILL_THUMBNAIL_DIR / f"{slug}.jpg"


def extract_frame(clip: Path, dest: Path, *, at_fraction: float = _SAMPLE_FRACTION) -> bool:
    """Write one downscaled frame of *clip* to *dest*; True when it lands.

    Seeks to *at_fraction* of the clip's duration (0 when the duration is unknown)
    and scales to ``_THUMBNAIL_HEIGHT``, keeping the aspect ratio. Uses the same
    Topaz ffmpeg and console-suppressed invocation the rest of the pipeline does.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # The probe is inside the try too: it also runs a binary, and one that
        # is not installed used to escape here, escape build_thumbnails and
        # take the whole tool's startup down -- silently, since pythonw.exe has
        # no console for the traceback.
        duration = duration_seconds(clip)
        timestamp = duration * at_fraction if duration else 0.0
        result = subprocess.run(
            [
                str(config.FFMPEG),
                "-nostdin",
                "-ss", f"{timestamp:.3f}",
                "-i", str(clip),
                "-frames:v", "1",
                "-vf", f"scale=-2:{_THUMBNAIL_HEIGHT}",
                "-y", str(dest),
            ],
            capture_output=True,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except OSError:
        log.exception("Could not build a thumbnail for %s", clip)
        return False
    return result.returncode == 0 and dest.is_file()


def build_thumbnails(
    examples: Mapping[str, Path],
    extract: Callable[[Path, Path], bool],
    cache_path_for: Callable[[str], Path],
):
    """Yield ``(action, thumbnail path)`` for each example that has, or gets, one.

    A cached frame is reused; otherwise one is extracted and cached. An act whose
    extraction fails is skipped, so its tile simply stays text-only.
    """
    for action, clip in examples.items():
        dest = cache_path_for(action)
        if dest.is_file() or extract(clip, dest):
            yield action, dest
