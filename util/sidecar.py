"""Where a video's metadata sidecar lives, and what the upscale stage names its output.

The library keeps metadata out of the video tree: a clip under ``VIDEO_LIBRARY_DIR``
has its JSON at the same relative path beneath ``METADATA_DIR``.  That mirroring is
the contract the downstream browser reads by, so it is expressed here once.

Stages that must locate a sidecar before the upscaled clip exists — prompt scraping
runs against ``1_sorted`` — reach it by naming the clip the upscale stage *will*
write, then mapping that path through :func:`sidecar_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import config


def upscaled_video_path(source: str, orient: str, sorted_stem: str) -> Path:
    """The clip the upscale stage writes for the ``1_sorted`` video *sorted_stem*."""
    return config.OUT_UPSCALED_DIR / orient / source / f"{sorted_stem}_topaz.mp4"


def sidecar_path(video: Path) -> Path:
    """The metadata JSON mirroring *video*'s path under ``METADATA_DIR``.

    The whole video library is mirrored: a clip's sidecar sits at the same path
    beneath ``METADATA_DIR`` as the clip sits beneath ``VIDEO_LIBRARY_DIR``
    (``2D/AI/2_outbox/x.mp4`` -> ``2D/AI/2_outbox/x.json``, ``2D/non_AI/larkin/
    y.mp4`` -> ``2D/non_AI/larkin/y.json``), so AI generation metadata and
    non-AI version families share one tree that parallels the video tree.

    A video that is *beside* that tree rather than inside it — Genau's delivered
    clips, which live at ``videos/genau/clips`` while the library is
    ``videos/videos`` — mirrors from the folder holding both, landing at
    ``metadata/genau/clips/y.json``.  Their kind (:mod:`util.video_type`) has to
    be recorded somewhere, and a delivered clip keeps the generation metadata it
    was made with rather than losing it at the door.

    Raises ``ValueError`` for a video under neither.
    """
    for root in (config.VIDEO_LIBRARY_DIR, config.VIDEO_SEARCH_ROOT):
        try:
            relative = video.relative_to(root)
        except ValueError:
            continue
        return (config.METADATA_DIR / relative).with_suffix(".json")
    raise ValueError(f"{video} is not in the video library")


def read(path: Path) -> dict:
    """A sidecar's payload — empty when it is absent or unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write(path: Path, payload: dict) -> None:
    """Serialize *payload* to *path*, creating the mirrored directory if need be."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _video_field(payload: dict, field: str) -> str:
    video = payload.get("video")
    if not isinstance(video, dict):
        return ""
    return str(video.get(field) or "")


def action_of(payload: dict) -> str:
    """The act a sidecar records, or ``""`` when it records none."""
    return _video_field(payload, "action")


# The key Fun Time leaves behind when its "wrong action" command empties
# ``video.action`` (see ``fun_time/media_metadata.py``).  It is written by that
# app and read by this one; only :func:`backfill.decisions.record_action` clears
# it, once the viewer has finally named the act.
WRONG_ACTION_FIELD = "wrong_action"


def wrong_action_of(payload: dict) -> str:
    """The act a viewer struck out as wrong, or ``""`` when none was.

    A clip that has this reads as unlabeled — the act is gone — but is not
    merely *unlabeled*: someone looked at it and said the label it had was
    wrong.  The backfill queue asks about those first.
    """
    return _video_field(payload, WRONG_ACTION_FIELD)
