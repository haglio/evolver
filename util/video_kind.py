from __future__ import annotations

from app_support.video_kind import TYPES
from shared_ui.orientation import ORIENTATIONS

BLOCK = "video"
FIELD = "type"

DURATION_FIELD = "duration_seconds"

ORIENTATION_FIELD = "orientation"

def orientation_of(payload: dict) -> str:
    return _word_recorded(payload, ORIENTATION_FIELD, ORIENTATIONS)


def _word_recorded(payload: dict, field: str, words: tuple[str, ...]) -> str:
    recorded = str(_block(payload).get(field) or "")
    return recorded if recorded in words else ""


def duration_of(payload: dict) -> float | None:
    seconds = _block(payload).get(DURATION_FIELD)
    return float(seconds) if isinstance(seconds, (int, float)) else None


def _block(payload: dict) -> dict:
    block = payload.get(BLOCK)
    return block if isinstance(block, dict) else {}


def stamped(payload: dict, video_kind: str) -> dict:
    return _recorded(payload, FIELD, _one_of(TYPES, video_kind, "a video type"))


def timed(payload: dict, duration_seconds: float) -> dict:
    if duration_seconds < 0:
        raise ValueError(f"not a running time: {duration_seconds!r}")
    return _recorded(payload, DURATION_FIELD, float(duration_seconds))


def oriented(payload: dict, orientation: str) -> dict:
    return _recorded(payload, ORIENTATION_FIELD,
                     _one_of(ORIENTATIONS, orientation, "an orientation"))


def _one_of(words: tuple[str, ...], word: str, what: str) -> str:
    if word not in words:
        raise ValueError(f"not {what}: {word!r}")
    return word


def _recorded(payload: dict, field: str, value) -> dict:
    return {**payload, BLOCK: {**_block(payload), field: value}}
