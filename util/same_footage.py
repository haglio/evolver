from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from util.frame_hashes import TOLERANCE, frame_hashes, frames_at

SAME_LENGTH_TOLERANCE_SECONDS = 0.5

MOMENTS = 16
AGREEING_MOMENTS = 10

BLOCK = "footage"
FIELD = "fingerprint"


def fingerprint(
    video: Path, seconds: float, *,
    grab: Callable[[Path, list[float]], np.ndarray] = frames_at,
) -> list[str] | None:
    frames = grab(video, [seconds * (moment + 0.5) / MOMENTS for moment in range(MOMENTS)])
    if len(frames) != MOMENTS:
        return None
    return [f"{value:016x}" for value in frame_hashes(frames).tolist()]


def fingerprint_of(payload: dict) -> list[str] | None:
    block = payload.get(BLOCK)
    recorded = block.get(FIELD) if isinstance(block, dict) else None
    return recorded if isinstance(recorded, list) and len(recorded) == MOMENTS else None


def fingerprinted(payload: dict, moments: list[str]) -> dict:
    block = payload.get(BLOCK)
    return {**payload, BLOCK: {**(block if isinstance(block, dict) else {}), FIELD: moments}}


def same_length(a: float, b: float) -> bool:
    return abs(a - b) <= SAME_LENGTH_TOLERANCE_SECONDS


def same_footage(a: Sequence[str], b: Sequence[str]) -> bool:
    agreeing = sum((int(x, 16) ^ int(y, 16)).bit_count() <= TOLERANCE for x, y in zip(a, b, strict=True))
    return agreeing >= AGREEING_MOMENTS


def join(ids: Mapping[str, str], pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
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
