"""Whether two differently named files hold one video, told by their pictures.

The naming rule (:mod:`util.version_groups`) finds a version by the thread its
name keeps back to its original. A copy saved under a name of its own keeps no
such thread, so the only thing left to go on is the footage: two files that run
the same length and show the same pictures at the same moments are one video.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from util.frame_hashes import TOLERANCE, frame_hashes, frames_at

# Two encodes of one video disagree on its length by a frame or two.
SAME_LENGTH_SECONDS = 0.5

# Measured on a real pair, 2026-09-16: two encodes of one scene agreed at 13 of
# 16 evenly spaced moments, and every same-length pair of different scenes in
# that folder agreed at none.
MOMENTS = 16
AGREEING_MOMENTS = 10

# Where a video's moments are kept: ``payload["footage"]["fingerprint"]``. They
# describe the footage rather than the file, so an upscale is handed its
# original's along with the rest of the sidecar.
BLOCK = "footage"
FIELD = "fingerprint"


def fingerprint(
    video: Path, seconds: float, *,
    grab: Callable[[Path, list[float]], np.ndarray] = frames_at,
) -> list[str] | None:
    """*video*'s picture at evenly spaced moments through its *seconds*, or None
    when ffmpeg could not read every one of them."""
    frames = grab(video, [seconds * (moment + 0.5) / MOMENTS for moment in range(MOMENTS)])
    if len(frames) != MOMENTS:
        return None
    return [f"{value:016x}" for value in frame_hashes(frames).tolist()]


def fingerprint_of(payload: dict) -> list[str] | None:
    block = payload.get(BLOCK)
    recorded = block.get(FIELD) if isinstance(block, dict) else None
    return recorded if isinstance(recorded, list) and len(recorded) == MOMENTS else None


def fingerprinted(payload: dict, moments: list[str]) -> dict:
    """*payload* with *moments* recorded on it -- a copy, leaving the original."""
    block = payload.get(BLOCK)
    return {**payload, BLOCK: {**(block if isinstance(block, dict) else {}), FIELD: moments}}


def same_length(a: float, b: float) -> bool:
    return abs(a - b) <= SAME_LENGTH_SECONDS


def same_footage(a: Sequence[str], b: Sequence[str]) -> bool:
    agreeing = sum((int(x, 16) ^ int(y, 16)).bit_count() <= TOLERANCE for x, y in zip(a, b))
    return agreeing >= AGREEING_MOMENTS


def join(ids: Mapping[str, str], pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """*ids* with every family in *pairs* folded into one, under its first id."""
    anchor: dict[str, str] = {}

    def root(family: str) -> str:
        while anchor.get(family, family) != family:
            family = anchor[family]
        return family

    for a, b in pairs:
        first, second = sorted((root(a), root(b)))
        if first != second:
            anchor[second] = first
    return {stem: root(family) for stem, family in ids.items()}
