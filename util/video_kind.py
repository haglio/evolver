"""What kind of video this is, how long it runs, and whether it is portrait or
landscape — the ``video`` block.

Facts about the file itself, recorded together on its metadata sidecar and
owned here so that the block has a single author: :mod:`tasks.video_kinds`
writes them, and everything else reads.

Four kinds, and every video in the library is exactly one of them.  The answer
lives on the video's metadata sidecar, in the ``video`` block beside the act and
the generation parameters, so that the apps *read* a kind rather than each
working one out for itself.  Working it out gives five answers to one question
— the folder a clip was delivered to, a source folder's name, a running time
against a threshold each app picks separately, the presence of a ``clip``
record, and "everything else" — disagreeing at the edges and impossible to
correct in one place.

Which the four are, and the order they settle in (a video that looks like two of
them is the earlier one):

``genau_flick``
    A flick in Genau's own folder.  It is delivered there and nothing
    else lives in it, so the lane is the whole test.

``excerpt``
    A scene carved out of a longer video — the ``clip`` record on its sidecar
    names the video it came out of and where in it.  A clip is a clip
    however long it runs, which is why it settles before the running time does.

``short``
    Anything running :data:`SHORT_MAX_SECONDS` or less.  Generated clips are all
    of them a few seconds long; a real scene never is.

``full_length``
    Everything else — the scene library, and the generated clips long enough to
    watch as one.  An unknown running time lands here too: a video nothing can
    measure is far likelier to be a scene than a loop, and the alternative is a
    fifth kind meaning "we never found out".

The running time is kept rather than thrown away once it has settled a kind.
An ffprobe is a process spawn, and a video does not change length, so the one
measurement answers every later question about how long something runs — which
is how :mod:`tasks.nonai_progress` weighs the non-AI upscale queue against the
part of the library already done without probing four hundred files a tick.
"""

from __future__ import annotations

from app_support import favorites
from shared_ui.orientation import ORIENTATIONS

from util import provenance, watch

GENAU_FLICK = "genau_flick"
CLIP = "excerpt"
SHORT = "short"
FULL_LENGTH = "full_length"

TYPES = (GENAU_FLICK, CLIP, SHORT, FULL_LENGTH)

SHORT_MAX_SECONDS = 10.0

BLOCK = "video"
FIELD = "type"

DURATION_FIELD = "duration_seconds"

ORIENTATION_FIELD = "orientation"

_OWN_FIELDS = frozenset({FIELD, DURATION_FIELD, ORIENTATION_FIELD})

_STAMPS = frozenset({watch.BLOCK, provenance.BLOCK, favorites.FAVORITE_KEY, favorites.PAGE_KEY})


def free_kind(*, genau: bool, clip: bool) -> str:
    if genau:
        return GENAU_FLICK
    if clip:
        return CLIP
    return ""


def classify(*, genau: bool, clip: bool, duration_seconds: float | None) -> str:
    free = free_kind(genau=genau, clip=clip)
    if free:
        return free
    if duration_seconds is not None and duration_seconds <= SHORT_MAX_SECONDS:
        return SHORT
    return FULL_LENGTH


def kind_of(payload: dict) -> str:
    return _word_recorded(payload, FIELD, TYPES)


def orientation_of(payload: dict) -> str:
    return _word_recorded(payload, ORIENTATION_FIELD, ORIENTATIONS)


def _word_recorded(payload: dict, field: str, words: tuple[str, ...]) -> str:
    recorded = str(_block(payload).get(field) or "")
    return recorded if recorded in words else ""


def duration_of(payload: dict) -> float | None:
    """The running time *payload* records, or ``None`` when it records none.

    ``None`` for a sidecar written before the field existed, and for one whose
    video could not be measured — both mean "ask ffprobe", which is what
    :mod:`tasks.video_kinds` does with the one measurement it is allowed.
    """
    seconds = _block(payload).get(DURATION_FIELD)
    return float(seconds) if isinstance(seconds, (int, float)) else None


def _block(payload: dict) -> dict:
    block = payload.get(BLOCK)
    return block if isinstance(block, dict) else {}


def only_the_video_itself(payload: dict) -> bool:
    besides_the_stamps = set(payload) - _STAMPS
    if not besides_the_stamps:
        return provenance.BLOCK in payload
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
