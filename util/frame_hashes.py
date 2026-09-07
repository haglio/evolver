"""Reading a video down to comparable frames, and finding one run inside another.

A carved clip is a literal excerpt of a library scene, so the scene's timeline
holds the clip's pictures verbatim. Sampling frames from both, hashing them and
looking for the offset that lines them up therefore answers a question the
filenames cannot -- which scene a clip came out of, and where in it.

Black bars come off both sides before any of that. A hash reads a frame as a
grid of cells, so it is a statement about where things sit in the picture -- and
a compilation that pillarboxed a 4:3 scene into a 16:9 frame has moved
everything inward by an eighth without changing a pixel of it. Bars are the
frame around a picture rather than part of it, so they are cut first and the
grid lands on the same content either side.

Nothing here reads the library or writes a sidecar: it takes paths and returns
numbers. :mod:`tasks.clip_match` is what walks the library with it.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from app_support.subprocess_utils import hidden_subprocess_kwargs

from util import ffprobe

log = logging.getLogger(__name__)

# The hash is 8 rows of 9 cells compared left-to-right, so a sampled frame is a
# whole multiple of that -- pooling then divides exactly and no pixel is dropped.
_ROWS, _COLS = 8, 9
SAMPLE_HEIGHT, SAMPLE_WIDTH = _ROWS * 4, _COLS * 4

# Both sides are sampled on one grid, so the worst a clip frame can be out by is
# half a step -- 60ms, less than two frames of the videos themselves.
SAMPLE_FPS = 8.0

# A frame survives re-encoding, rescaling and upscaling with its hash almost but
# not quite intact, so "the same picture" is a small Hamming distance, not zero.
TOLERANCE = 8

# How far either side of an offset its own frames can land, in samples. The two
# videos are sampled off different source frame rates, so one excerpt's frames
# answer to a small spread of offsets rather than to exactly one.
JITTER = 1

# How much of a clip has to turn up at one offset before that offset is the
# answer. A real excerpt places nearly all of itself; scattered lookalikes place
# a frame or two each, so anything in between is a wide, safe gap.
MIN_SCORE = 0.25

_POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)

# Where in a video to look for its bars, as fractions of its runtime, and for how
# long each time. Bars are a constant of the encode, so a few seconds anywhere
# show them -- but a fade or a dark shot reads as bars that are not there, and
# cropping a scene its clip does not crop is how a real pair *stops* matching. So
# several windows are unioned: the widest picture any of them saw is the one
# really there, which makes a mistake here cost a crop rather than a match.
PROBE_POINTS = (0.2, 0.5, 0.8)
PROBE_SECONDS = 4.0

# ffmpeg's own reading of "black" (anything this dark), and the multiple it
# rounds the rectangle it finds to.
_CROP_LIMIT, _CROP_ROUND = 24, 2

# A picture smaller than this much of the frame is a dark scene being read as
# bars rather than bars: no real letterbox takes half the height.
MIN_PICTURE_FRACTION = 0.5

_CROP_REPORT = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def picture_crop(
    reports: Iterable[str], width: int, height: int,
) -> tuple[int, int, int, int] | None:
    """The ``crop=w:h:x:y`` of the picture inside *width* x *height*, or None.

    None means "use the frame as it is" -- either nothing was measured, or what
    was measured is the whole frame, or it is so small that a dark shot is the
    likelier explanation. Every *reports* rectangle is taken in, since a window
    can only ever find bars that are not there (see :data:`PROBE_POINTS`), and
    the union of them all is the least-cropped reading.
    """
    corners = [
        (int(x), int(y), int(x) + int(w), int(y) + int(h))
        for report in reports
        for w, h, x, y in _CROP_REPORT.findall(report)
    ]
    if not corners:
        return None
    left = min(corner[0] for corner in corners)
    upper = min(corner[1] for corner in corners)
    right = max(corner[2] for corner in corners)
    lower = max(corner[3] for corner in corners)

    # Chroma is subsampled, so an odd rectangle is one ffmpeg's crop refuses.
    # Rounding outward keeps this the widest reading rather than the tightest.
    left, upper = max(0, left - left % 2), max(0, upper - upper % 2)
    crop_width = min(width - left, right - left + right % 2)
    crop_height = min(height - upper, lower - upper + lower % 2)
    crop_width, crop_height = crop_width - crop_width % 2, crop_height - crop_height % 2

    if crop_width >= width and crop_height >= height:
        return None
    if crop_width < width * MIN_PICTURE_FRACTION or crop_height < height * MIN_PICTURE_FRACTION:
        return None
    return crop_width, crop_height, left, upper


def _cropdetect(video: Path, at: float) -> str:
    """What ffmpeg's cropdetect says about the seconds of *video* from *at*."""
    command = [
        "ffmpeg", "-nostats", "-ss", f"{at:.3f}", "-t", str(PROBE_SECONDS),
        "-i", str(video), "-an",
        # reset=0: the rectangle accumulates over the whole window rather than
        # being re-measured per frame, so one dark moment cannot narrow it.
        "-vf", f"cropdetect={_CROP_LIMIT}:{_CROP_ROUND}:0", "-f", "null", "-",
    ]
    try:
        return subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            **hidden_subprocess_kwargs(),
        ).stderr.decode(errors="replace")
    except OSError as exc:
        log.warning("could not measure %s: %s", video.name, exc)
        return ""


def content_crop(video: Path) -> tuple[int, int, int, int] | None:
    """The ``crop=w:h:x:y`` that leaves *video*'s picture without its bars.

    None when it has none worth cutting, which is most videos.
    """
    dimensions = ffprobe.video_dimensions(video)
    duration = ffprobe.duration_seconds(video)
    if dimensions is None or duration is None:
        return None
    width, height = dimensions
    return picture_crop(
        [_cropdetect(video, duration * point) for point in PROBE_POINTS], width, height,
    )


def sample_frames(video: Path, fps: float) -> np.ndarray:
    """*video* decoded to gray thumbnails, *fps* of them a second.

    Its black bars are cropped off first, so the thumbnails hold the picture and
    nothing else -- a pillarboxed clip and the unpadded scene it came out of are
    the same picture, and have to reach the hash as the same grid of cells.

    Empty when ffmpeg cannot read the file, which leaves that video matching
    nothing rather than stopping the batch. Files with damaged frames do decode,
    complaining on stderr the whole way -- held back unless the run really fails,
    since a batch over hundreds of videos is unreadable otherwise.
    """
    crop = content_crop(video)
    filters = [f"fps={fps}"]
    if crop is not None:
        filters.append("crop={}:{}:{}:{}".format(*crop))
    # Averaging the whole source block, rather than sampling a few pixels of it,
    # is what makes a 4K upscale thumbnail like its 540p original.
    filters.append(f"scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area")
    command = [
        "ffmpeg", "-v", "error", "-i", str(video), "-an",
        "-vf", ",".join(filters),
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    try:
        raw = subprocess.run(
            command, capture_output=True, check=True, **hidden_subprocess_kwargs(),
        ).stdout
    except subprocess.CalledProcessError as exc:
        log.warning("could not sample %s: %s", video.name, exc.stderr.decode(errors="replace"))
        raw = b""
    except OSError as exc:
        log.warning("could not sample %s: %s", video.name, exc)
        raw = b""
    pixels = SAMPLE_HEIGHT * SAMPLE_WIDTH
    count = len(raw) // pixels
    return np.frombuffer(raw[: count * pixels], dtype=np.uint8).reshape(
        count, SAMPLE_HEIGHT, SAMPLE_WIDTH
    )


def frame_hashes(frames: np.ndarray) -> np.ndarray:
    """A 64-bit difference hash per frame of *frames* (n x height x width, gray).

    Each frame is mean-pooled to 8x9 cells and every cell compared with its
    right-hand neighbor. Reading *relative* brightness is what lets a clip's
    frame match the same frame in a scene encoded at another resolution,
    bitrate or gamma.
    """
    pooled = _pool(frames)
    bits = pooled[:, :, 1:] > pooled[:, :, :-1]
    return np.packbits(bits.reshape(len(frames), 64), axis=1).view(">u8").ravel()


def _pool(frames: np.ndarray) -> np.ndarray:
    """*frames* averaged down to the hash's 8x9 grid of cells."""
    count, height, width = frames.shape
    return frames.reshape(
        count, _ROWS, height // _ROWS, _COLS, width // _COLS,
    ).mean(axis=(2, 4))


@dataclass(frozen=True)
class Alignment:
    """Where a clip sits in a scene, and how much of it was found there."""

    offset: float
    score: float


def align(clip: np.ndarray, scene: np.ndarray, *, fps: float) -> Alignment | None:
    """Where *clip*'s frames sit in *scene*'s, or None if they do not.

    Both are frame-hash runs sampled at *fps*. Every near-equal pair of frames
    votes for the offset that would explain it; the offset the most clip frames
    agree on wins, and has to carry :data:`MIN_SCORE` of the clip to count.

    Neighboring offsets count together. Sampling 8 frames a second off a 24fps
    scene lands on exact source frames and off a 30fps clip does not, so one
    excerpt's frames answer to offsets a bucket either side of the true one; the
    single best bucket holds only a fraction of a real match.
    """
    close = _distances(clip, scene) <= TOLERANCE
    if not close.any():
        return None
    clip_frame, scene_frame = np.nonzero(close)
    shift = scene_frame - clip_frame
    best = _peak(shift)
    # Distinct frames, since one clip frame can answer to every offset in the
    # window; without that a still moment could score above a whole excerpt.
    backers = np.unique(clip_frame[np.abs(shift - best) <= JITTER])
    score = len(backers) / len(clip)
    return Alignment(offset=best / fps, score=score) if score >= MIN_SCORE else None


def _peak(shift: np.ndarray) -> int:
    """The offset whose window of neighbors carries the most votes."""
    low = int(shift.min())
    counts = np.bincount(shift - low)
    window = np.convolve(counts, np.ones(2 * JITTER + 1, dtype=int), mode="same")
    return int(window.argmax()) + low


def _distances(clip: np.ndarray, scene: np.ndarray) -> np.ndarray:
    """Hamming distance between every clip hash and every scene hash."""
    xor = (clip[:, None] ^ scene[None, :]).view(np.uint8).reshape(len(clip), len(scene), 8)
    return _POPCOUNT[xor].sum(axis=2, dtype=np.uint8)


@dataclass(frozen=True)
class Match:
    """The one candidate clip a scene turned out to contain."""

    clip: Path
    offset: float
    score: float


def locate(scene: np.ndarray, candidates: dict[Path, np.ndarray], *, fps: float) -> Match | None:
    """Which of *candidates* was cut from *scene*, and where, or None.

    Candidates come from the names -- every clip whose performer the scene's
    filename mentions -- so most of them were cut from the same performer's other
    scenes and belong nowhere in this one. The best-aligning candidate wins; a
    scene that never made it into a compilation has no aligning candidate at all.
    """
    found = {
        clip: alignment
        for clip, hashes in candidates.items()
        if (alignment := align(hashes, scene, fps=fps)) is not None
    }
    if not found:
        return None
    clip = max(found, key=lambda candidate: found[candidate].score)
    return Match(clip=clip, offset=found[clip].offset, score=found[clip].score)
