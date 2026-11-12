from __future__ import annotations

from app_support import favorites, video_ids
from app_support.video_kind import TYPES
from shared_ui.orientation import ORIENTATIONS

from util import provenance, watch

BLOCK = "video"
FIELD = "type"

DURATION_FIELD = "duration_seconds"

ORIENTATION_FIELD = "orientation"

_OWN_FIELDS = frozenset({FIELD, DURATION_FIELD, ORIENTATION_FIELD})

_STAMPS = frozenset({watch.BLOCK, provenance.BLOCK, favorites.FAVORITE_KEY, favorites.PAGE_KEY})
_ABOUT_THE_FILE = frozenset({provenance.BLOCK, video_ids.ID_KEY})


def kind_of(payload: dict) -> str:
    return _word_recorded(payload, FIELD, TYPES)


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


def only_the_video_itself(payload: dict) -> bool:
    besides_the_stamps = set(payload) - _STAMPS - {video_ids.ID_KEY}
    if not besides_the_stamps:
        return bool(_ABOUT_THE_FILE & set(payload))
    if besides_the_stamps != {BLOCK}:
        return False
    block = payload[BLOCK]
    return isinstance(block, dict) and set(block) <= _OWN_FIELDS


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
