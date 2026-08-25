"""What kind of video this is — the one question every app in the family asks.

Four kinds, and every video in the library is exactly one of them.  The answer
lives on the video's metadata sidecar, in the ``video`` block beside the act and
the generation parameters, so that the apps *read* a kind rather than each
working one out for itself.  They used to work it out: the folder a clip was
delivered to, a source folder's name, a running time compared against a
threshold each app picked separately, the presence of a ``clip`` record, and
"everything else" — five answers to one question, disagreeing at the edges and
impossible to correct in one place.

Which the four are, and the order they settle in (a video that looks like two of
them is the earlier one):

``genau_clip``
    A looping clip in Genau's own folder.  It is delivered there and nothing
    else lives in it, so the lane is the whole test.

``excerpt``
    A scene carved out of a longer video — the ``clip`` record on its sidecar
    names the video it came out of and where in it.  An excerpt is an excerpt
    however long it runs, which is why it settles before the running time does.

``short``
    Anything running :data:`SHORT_MAX_SECONDS` or less.  Generated clips are all
    of them a few seconds long; a real scene never is.

``full_length``
    Everything else — the scene library, and the generated clips long enough to
    watch as one.  An unknown running time lands here too: a video nothing can
    measure is far likelier to be a scene than a loop, and the alternative is a
    fifth kind meaning "we never found out".
"""

from __future__ import annotations

GENAU_CLIP = "genau_clip"
EXCERPT = "excerpt"
SHORT = "short"
FULL_LENGTH = "full_length"

#: Every kind, in the order :func:`classify` settles them.
TYPES = (GENAU_CLIP, EXCERPT, SHORT, FULL_LENGTH)

#: A video runs short when it is no longer than this.  One number for the whole
#: family: Nau split its library at 60 seconds and Warm Gun at 10, so a clip
#: between the two was a short on the phone and a full-length scene on the
#: desktop — the disagreement this field exists to end.
SHORT_MAX_SECONDS = 10.0

#: Where the kind sits on the sidecar: ``payload["video"]["type"]``.
BLOCK = "video"
FIELD = "type"


def classify(*, genau: bool, excerpt: bool, duration_seconds: float | None) -> str:
    """Which kind a video is, from the three signals that can identify one.

    *genau* is whether it sits in Genau's clips folder, *excerpt* whether
    something carved it out of a longer video, and *duration_seconds* its
    running time — ``None`` when it could not be measured.
    """
    if genau:
        return GENAU_CLIP
    if excerpt:
        return EXCERPT
    if duration_seconds is not None and duration_seconds <= SHORT_MAX_SECONDS:
        return SHORT
    return FULL_LENGTH


def type_of(payload: dict) -> str:
    """The kind *payload* records, or ``""`` when it records none.

    Empty is the ordinary answer for a sidecar written before this field
    existed, not an error: every reader falls back to what it did before.
    """
    block = payload.get(BLOCK)
    if not isinstance(block, dict):
        return ""
    recorded = str(block.get(FIELD) or "")
    return recorded if recorded in TYPES else ""


def stamped(payload: dict, video_type: str) -> dict:
    """*payload* with *video_type* recorded on it — a copy, leaving the original.

    Creates the ``video`` block for the sidecars that have none: a non-AI scene
    carries no generation parameters, so its sidecar holds nothing but a version
    family until the kind arrives to join it.
    """
    if video_type not in TYPES:
        raise ValueError(f"not a video type: {video_type!r}")
    stamped_payload = dict(payload)
    block = stamped_payload.get(BLOCK)
    block = dict(block) if isinstance(block, dict) else {}
    block[FIELD] = video_type
    stamped_payload[BLOCK] = block
    return stamped_payload
