"""Where a video's metadata sidecar lives, and what the upscale stage names its output.

The library keeps generation metadata out of the video tree: a clip under ``AI_DIR``
has its JSON at the same relative path beneath ``METADATA_DIR``.  That mirroring is
the contract the downstream browser reads by, so it is expressed here once.

Stages that must locate a sidecar before the upscaled clip exists — prompt scraping
runs against ``1_sorted`` — reach it by naming the clip the upscale stage *will*
write, then mapping that path through :func:`sidecar_path`.
"""

from __future__ import annotations

from pathlib import Path

import config


def upscaled_video_path(source: str, orient: str, sorted_stem: str) -> Path:
    """The clip the upscale stage writes for the ``1_sorted`` video *sorted_stem*."""
    return config.OUT_UPSCALED_DIR / orient / source / f"{sorted_stem}_topaz.mp4"


def sidecar_path(video: Path) -> Path:
    """The metadata JSON mirroring *video*'s path under ``METADATA_DIR``."""
    return (config.METADATA_DIR / video.relative_to(config.AI_DIR)).with_suffix(".json")
