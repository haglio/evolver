"""Asking ffprobe about a video, one process per question at most.

Every function here answers None (or "") when ffprobe cannot say, including
when it is not installed at all: these are called from the tray pipeline and
from the backfill tool, and the tool has no console for a traceback to land
in -- an escaping FileNotFoundError left it never appearing on screen.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from util import orientation

# Width, height and the rotation tag in one invocation. ffprobe takes several
# -show_entries sections at once, and the tag is optional, so the CSV comes
# back with two fields or three.
_GEOMETRY_ENTRIES = "stream=width,height:stream_tags=rotate"


def _stream_geometry(file: Path) -> tuple[int, int, int] | None:
    """(width, height, rotation degrees) for the first video stream, or None.

    One process for all three. The sort stage asks this once per incoming file,
    so a batch of a hundred clips used to be three hundred process spawns --
    and on Windows the spawn is the expensive part, not the probing.

    A rotation nothing can parse counts as none: the width and height are still
    good, and a tag this cannot read only means the clip is not rotated as far
    as it can tell.
    """
    fields = _probe(file, _GEOMETRY_ENTRIES).split(",")
    if len(fields) not in (2, 3):
        return None
    try:
        width, height = int(fields[0]), int(fields[1])
    except ValueError:
        return None
    rotation = 0
    if len(fields) == 3:
        try:
            rotation = int(fields[2])
        except ValueError:
            rotation = 0
    return width, height, rotation


def video_dimensions(file: Path) -> tuple[int, int] | None:
    """The (width, height) of a file's first video stream, or None if unavailable.

    Raw stored dimensions — rotation is not applied. Callers that need display
    orientation (see :func:`get_orientation`) fold the rotate tag in themselves.
    """
    geometry = _stream_geometry(file)
    return None if geometry is None else geometry[:2]


def get_orientation(file: Path) -> str:
    """Return 'landscape', 'portrait', or 'unknown' based on the first video stream."""
    geometry = _stream_geometry(file)
    if geometry is None:
        return orientation.UNKNOWN
    width, height, rotation = geometry
    if rotation % 180 != 0:
        width, height = height, width
    # Square counts as landscape: it is a tie the sorted-folder choice has to
    # break somehow, and this is the side it has always fallen.
    return orientation.PORTRAIT if height > width else orientation.LANDSCAPE


def duration_seconds(file: Path) -> float | None:
    """The container duration of *file* in seconds, or None if unavailable."""
    try:
        return float(_probe_format(file, "format=duration"))
    except ValueError:
        return None


def frame_fingerprint(file: Path) -> tuple[float, int] | None:
    """The (fps, frame count) of *file*, or None when the container counts no frames.

    Enough to tell one cut of footage from another: a re-encode that changes
    either number is a different video as far as anything holding frame indices
    is concerned.
    """
    fields = _probe(file, "stream=r_frame_rate,nb_frames").split(",")
    if len(fields) != 2:
        return None
    numerator, _, denominator = fields[0].partition("/")
    try:
        return int(numerator) / int(denominator or 1), int(fields[1])
    except (ValueError, ZeroDivisionError):
        return None


def videoai_tag(file: Path) -> str:
    """The Topaz ``videoai`` metadata tag of *file* — empty when untagged."""
    return _probe_format(file, "format_tags=videoai")


def _probe(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-select_streams", "v:0", "-show_entries", show_entries, str(file)])


def _probe_format(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-show_entries", show_entries, str(file)])


def _run_ffprobe(args: list[str]) -> str:
    """ffprobe's answer, or "" when there is none to be had.

    OSError covers ffprobe not being installed, which is the case that used to
    escape: every function here documents itself as answering None when the
    probe is unavailable, and none of them did. check=False is deliberate --
    a non-zero exit means ffprobe had nothing to say about this file, which is
    the same "" as any other silence.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "csv=p=0", *args],
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return ""
    return result.stdout.strip()
