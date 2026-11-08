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

_ROWS, _COLS = 8, 9
SAMPLE_HEIGHT, SAMPLE_WIDTH = _ROWS * 4, _COLS * 4

_WORST_MATCH_MISALIGNMENT_SECONDS = 0.0625
SAMPLE_FPS = 1 / (2 * _WORST_MATCH_MISALIGNMENT_SECONDS)

TOLERANCE = 8

JITTER = 1

MIN_SHARE_OF_THE_CLIP_AT_ONE_OFFSET = 0.25

_POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)

PROBE_POINTS = (0.2, 0.5, 0.8)
PROBE_SECONDS = 4.0

# ffmpeg's cropdetect: below 24 is black, rounded to 2, reset 0 grows one box over the window.
_CROP_LIMIT, _CROP_ROUND, _CROPDETECT_NEVER_RESETS = 24, 2, 0

REAL_LETTERBOX_MIN_CONTENT = 0.5

_CROP_REPORT = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def content_crop_in(
    reports: Iterable[str], width: int, height: int,
) -> tuple[int, int, int, int] | None:
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

    # ffmpeg's crop refuses an odd rectangle (subsampled chroma).
    left, upper = max(0, left - left % 2), max(0, upper - upper % 2)
    crop_width = min(width - left, right - left + right % 2)
    crop_height = min(height - upper, lower - upper + lower % 2)
    crop_width, crop_height = crop_width - crop_width % 2, crop_height - crop_height % 2

    if crop_width >= width and crop_height >= height:
        return None
    if crop_width < width * REAL_LETTERBOX_MIN_CONTENT or crop_height < height * REAL_LETTERBOX_MIN_CONTENT:
        return None
    return crop_width, crop_height, left, upper


def _cropdetect(video: Path, at: float) -> str:
    command = [
        "ffmpeg", "-nostats", "-ss", f"{at:.3f}", "-t", str(PROBE_SECONDS),
        "-i", str(video), "-an",
        "-vf", f"cropdetect={_CROP_LIMIT}:{_CROP_ROUND}:{_CROPDETECT_NEVER_RESETS}",
        "-f", "null", "-",
    ]
    try:
        return subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
            **hidden_subprocess_kwargs(),
        ).stderr.decode(errors="replace")
    except OSError as exc:
        log.warning("could not measure %s: %s", video.name, exc)
        return ""


def content_crop(video: Path) -> tuple[int, int, int, int] | None:
    dimensions = ffprobe.video_dimensions(video)
    duration = ffprobe.duration_seconds(video)
    if dimensions is None or duration is None:
        return None
    width, height = dimensions
    return content_crop_in(
        [_cropdetect(video, duration * point) for point in PROBE_POINTS], width, height,
    )


def sample_frames(video: Path, fps: float) -> np.ndarray:
    filters = ",".join([f"fps={fps}", *_content_filters(content_crop(video))])
    return _thumbnails(_decode(video, ["-i", str(video), "-an", "-vf", filters]))


def frames_at(video: Path, seconds: Iterable[float]) -> np.ndarray:
    filters = ",".join(_content_filters(content_crop(video)))
    moments = [
        _thumbnails(_decode(video, ["-ss", f"{at:.3f}", "-i", str(video), "-an",
                                    "-frames:v", "1", "-vf", filters]))
        for at in seconds
    ]
    return np.concatenate([_thumbnails(b""), *moments])


def _content_filters(crop: tuple[int, int, int, int] | None) -> list[str]:
    bars = [] if crop is None else ["crop={}:{}:{}:{}".format(*crop)]
    # ffmpeg's area scaler averages whole source blocks: a 4K upscale shrinks like its 540p original.
    return [*bars, f"scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"]


def _decode(video: Path, arguments: list[str]) -> bytes:
    command = ["ffmpeg", "-v", "error", *arguments, "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    try:
        return subprocess.run(
            command, capture_output=True, check=True,
            **hidden_subprocess_kwargs(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS),
        ).stdout
    except subprocess.CalledProcessError as exc:
        log.warning("could not sample %s: %s", video.name, exc.stderr.decode(errors="replace"))
    except OSError as exc:
        log.warning("could not sample %s: %s", video.name, exc)
    return b""


def _thumbnails(raw: bytes) -> np.ndarray:
    pixels = SAMPLE_HEIGHT * SAMPLE_WIDTH
    count = len(raw) // pixels
    return np.frombuffer(raw[: count * pixels], dtype=np.uint8).reshape(
        count, SAMPLE_HEIGHT, SAMPLE_WIDTH
    )


def frame_hashes(frames: np.ndarray) -> np.ndarray:
    pooled = _pool(frames)
    bits = pooled[:, :, 1:] > pooled[:, :, :-1]
    return np.packbits(bits.reshape(len(frames), 64), axis=1).view(">u8").ravel()


def _pool(frames: np.ndarray) -> np.ndarray:
    count, height, width = frames.shape
    return frames.reshape(
        count, _ROWS, height // _ROWS, _COLS, width // _COLS,
    ).mean(axis=(2, 4))


@dataclass(frozen=True)
class Alignment:
    offset: float
    score: float


def align(clip: np.ndarray, scene: np.ndarray, *, fps: float) -> Alignment | None:
    close = _distances(clip, scene) <= TOLERANCE
    if not close.any():
        return None
    clip_frame, scene_frame = np.nonzero(close)
    shift = scene_frame - clip_frame
    best = _peak(shift)
    backers = np.unique(clip_frame[np.abs(shift - best) <= JITTER])
    score = len(backers) / len(clip)
    return Alignment(offset=best / fps, score=score) if score >= MIN_SHARE_OF_THE_CLIP_AT_ONE_OFFSET else None


def _peak(shift: np.ndarray) -> int:
    low = int(shift.min())
    counts = np.bincount(shift - low)
    window = np.convolve(counts, np.ones(2 * JITTER + 1, dtype=int), mode="same")
    return int(window.argmax()) + low


def _distances(clip: np.ndarray, scene: np.ndarray) -> np.ndarray:
    xor = (clip[:, None] ^ scene[None, :]).view(np.uint8).reshape(len(clip), len(scene), 8)
    return _POPCOUNT[xor].sum(axis=2, dtype=np.uint8)


@dataclass(frozen=True)
class Match:
    clip: Path
    offset: float
    score: float


def locate(scene: np.ndarray, candidates: dict[Path, np.ndarray], *, fps: float) -> Match | None:
    found = {
        clip: alignment
        for clip, hashes in candidates.items()
        if (alignment := align(hashes, scene, fps=fps)) is not None
    }
    if not found:
        return None
    clip = max(found, key=lambda candidate: found[candidate].score)
    return Match(clip=clip, offset=found[clip].offset, score=found[clip].score)
