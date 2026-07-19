"""Stage: record each non-AI clip's version family in a metadata sidecar.

Real-footage clips carry no generation metadata, but Fun Time's Nau player
still wants to fold an original together with its Topaz-enhanced variants into
one rotation slot. This stage is the source of truth for that grouping: it
scans every non_AI bucket, families the clips by name (:mod:`util.version_groups`)
plus the pairs ``config.NONAI_VERSION_OVERRIDES`` declares, and writes each a
sidecar — mirrored under ``METADATA_DIR`` exactly like the AI tree — recording
its family id and whether it is a processed variant.

Being the source of truth means it rewrites ``version.group`` on every run, so
editing a sidecar by hand does not hold: an override is the way to correct one.

New clips get grouped on the next run; sidecars for clips that have since moved
or been deleted are pruned, so the metadata tree stays a faithful record of the
library Evolver knows about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import sidecar
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets
from util.variants import is_processed_stem, strip_processing_suffixes
from util.version_groups import group_ids

log = logging.getLogger(__name__)


@dataclass
class NonAiGroupResult:
    grouped: int = 0
    families: int = 0
    written: int = 0
    pruned: int = 0

    @property
    def ok(self) -> bool:
        # Grouping is bookkeeping over whatever files exist; there is no failure
        # mode that should fail the pipeline. The field exists so the stage
        # reads like its siblings.
        return True


def run() -> NonAiGroupResult:
    """Group every non-AI clip and record its family in a mirrored sidecar."""
    log.info("=== Stage: group non-AI versions ===")
    result = NonAiGroupResult()
    expected: set[Path] = set()

    for bucket in buckets():
        videos = [
            video
            for video in sorted(bucket.rglob("*"))
            if is_finalized_video_file(video, config.VIDEO_EXTENSIONS)
        ]
        if not videos:
            continue
        ids = group_ids([video.stem for video in videos], config.NONAI_VERSION_OVERRIDES)
        # A `clip` object (compilation, source, performer) describes one carved
        # scene, and its re-encodes are the same scene — so an upscaled variant
        # inherits it and stays a navigable short. Keying that on the *family*
        # would be too broad: a family is name-derived, so a full scene the user
        # already owned can share it with a clip carved from the same movie, and
        # would wrongly be marked a clip. Key on the stripped stem instead, which
        # only ever matches genuine re-encodes of that one file.
        existing_by_video = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
        clip_by_origin: dict[str, dict] = {}
        for video in videos:
            clip = existing_by_video[video].get("clip")
            if isinstance(clip, dict):
                clip_by_origin.setdefault(strip_processing_suffixes(video.stem), clip)
        for video in videos:
            payload = dict(existing_by_video[video])
            payload["version"] = {
                "group": ids[video.stem],
                "processed": is_processed_stem(video.stem),
            }
            origin_clip = clip_by_origin.get(strip_processing_suffixes(video.stem))
            if origin_clip is not None:
                payload["clip"] = origin_clip
            path = sidecar.sidecar_path(video)
            expected.add(path)
            if existing_by_video[video] != payload:
                sidecar.write(path, payload)
                result.written += 1
        result.grouped += len(videos)
        result.families += len(set(ids.values()))

    result.pruned = _prune_orphans(expected)
    log.info(
        "Non-AI grouping: %d clip(s) in %d family(ies); wrote %d, pruned %d sidecar(s).",
        result.grouped, result.families, result.written, result.pruned,
    )
    return result


def _prune_orphans(expected: set[Path]) -> int:
    """Delete non-AI sidecars no current clip maps to (moved or removed files)."""
    pruned = 0
    for bucket in buckets():
        bucket_metadata = config.METADATA_DIR / bucket.relative_to(config.VIDEO_LIBRARY_DIR)
        if not bucket_metadata.is_dir():
            continue
        for json_path in bucket_metadata.rglob("*.json"):
            if json_path not in expected:
                try:
                    json_path.unlink()
                    pruned += 1
                except OSError:
                    log.exception("Could not prune stale non-AI sidecar: %s", json_path)
    return pruned
