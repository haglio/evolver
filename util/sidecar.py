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
from util.json_store import atomic_write_text, read_dict
from util.variants import upscaled_stem


def upscaled_video_path(
    source: str, orient: str, sorted_stem: str, outbox_dir: Path | None = None,
) -> Path:
    """The clip the upscale stage writes for the ``1_sorted`` video *sorted_stem*.

    *outbox_dir* is the tree it will be written under; without one, the
    configured outbox answers. The upscale stage passes the root it was itself
    given, so the path it checks for and the path it writes cannot be two
    different trees.
    """
    outbox_dir = config.OUT_UPSCALED_DIR if outbox_dir is None else outbox_dir
    return outbox_dir / orient / source / f"{upscaled_stem(sorted_stem)}.mp4"


def sidecar_path(video: Path) -> Path:
    """The metadata JSON mirroring *video*'s path under ``METADATA_DIR``.

    The whole video library is mirrored: a clip's sidecar sits at the same path
    beneath ``METADATA_DIR`` as the clip sits beneath ``VIDEO_LIBRARY_DIR``
    (``2D/AI/2_outbox/x.mp4`` -> ``2D/AI/2_outbox/x.json``, ``2D/non_AI/larkin/
    y.mp4`` -> ``2D/non_AI/larkin/y.json``), so AI generation metadata and
    non-AI version families share one tree that parallels the video tree.
    """
    return (config.METADATA_DIR / video.relative_to(config.VIDEO_LIBRARY_DIR)).with_suffix(".json")


def read(path: Path) -> dict:
    """A sidecar's payload — empty when it is absent or unreadable."""
    return read_dict(path)


def write(path: Path, payload: dict) -> None:
    """Serialize *payload* to *path*, creating the mirrored directory if need be.

    Written atomically because this is the one format three apps write: Fun
    Time stamps a watch onto one while a pipeline stage is rewriting it, and a
    reader must see the old file or the new one, never half of either.
    """
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


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
