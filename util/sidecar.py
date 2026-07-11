"""Where a video's metadata sidecar lives, and what the upscale stage names its output.

The library keeps generation metadata out of the video tree: a clip under ``AI_DIR``
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
    """The metadata JSON mirroring an AI *video*'s path under ``METADATA_DIR``."""
    return (config.METADATA_DIR / video.relative_to(config.AI_DIR)).with_suffix(".json")


def nonai_sidecar_path(video: Path) -> Path:
    """The metadata JSON mirroring a non-AI *video*'s path under ``METADATA_DIR``.

    The non_AI tree gets the same mirrored-sidecar treatment as the AI tree, so
    the version-grouping stage can record which family each real-footage clip
    belongs to alongside the AI generation metadata.
    """
    return (config.METADATA_DIR / video.relative_to(config.NON_AI_DIR)).with_suffix(".json")


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


def action_of(payload: dict) -> str:
    """The act a sidecar records, or ``""`` when it records none."""
    video = payload.get("video")
    if not isinstance(video, dict):
        return ""
    return str(video.get("action") or "")
