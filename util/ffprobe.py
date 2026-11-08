from __future__ import annotations

import logging
import subprocess
from fractions import Fraction
from pathlib import Path

from shared_ui.orientation import orientation_of_size

from util import orientation

log = logging.getLogger(__name__)

# A kill does not end a probe stuck on a stalled pCloud file, so stop waiting after this long.
ANSWER_WITHIN_S = 60

# One ffprobe for all three: on Windows starting a process costs more than the probe itself.
_GEOMETRY_ENTRIES = "stream=width,height:stream_tags=rotate"
_ROTATION_FIELD = 2


def _stream_geometry(file: Path) -> tuple[int, int, int] | None:
    fields = _probe(file, _GEOMETRY_ENTRIES).split(",")
    if len(fields) not in (2, 3):
        return None
    try:
        width, height = int(fields[0]), int(fields[1])
    except ValueError:
        return None
    rotation = 0
    if len(fields) > _ROTATION_FIELD:
        try:
            rotation = int(fields[_ROTATION_FIELD])
        except ValueError:
            rotation = 0
    return width, height, rotation


def video_dimensions(file: Path) -> tuple[int, int] | None:
    geometry = _stream_geometry(file)
    return None if geometry is None else geometry[:2]


def orientation_of(file: Path) -> str:
    geometry = _stream_geometry(file)
    if geometry is None:
        return orientation.UNKNOWN
    width, height, rotation = geometry
    if rotation % 180 != 0:
        width, height = height, width
    return orientation_of_size(width, height)


def duration_seconds(file: Path) -> float | None:
    try:
        return float(_probe_format(file, "format=duration"))
    except ValueError:
        return None


def frame_rate(file: Path) -> Fraction | None:
    return _rate(_probe(file, "stream=r_frame_rate"))


def _rate(said: str) -> Fraction | None:
    try:
        return Fraction(said)
    except (ValueError, ZeroDivisionError):
        return None


def videoai_tag(file: Path) -> str:
    return _probe_format(file, "format_tags=videoai")


def has_sound(file: Path) -> bool:
    return "audio" in _run_ffprobe(
        ["-select_streams", "a", "-show_entries", "stream=codec_type", str(file)])


def _probe(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-select_streams", "v:0", "-show_entries", show_entries, str(file)])


def _probe_format(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-show_entries", show_entries, str(file)])


def _run_ffprobe(args: list[str]) -> str:
    try:
        process = subprocess.Popen(
            ["ffprobe", "-v", "error", "-of", "csv=p=0", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return ""
    try:
        said, _ = process.communicate(timeout=ANSWER_WITHIN_S)
    except subprocess.TimeoutExpired:
        log.warning("ffprobe gave no answer about %s in %ds; leaving it", args[-1], ANSWER_WITHIN_S)
        process.kill()
        return ""
    return said.strip()
