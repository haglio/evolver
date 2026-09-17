"""Stage: record each non-AI clip's version family in a metadata sidecar.

Real-footage clips carry no generation metadata, but Fun Time's main player
still wants to fold an original together with its Topaz-enhanced variants into
one rotation slot. This stage is the source of truth for that grouping: it
scans every non_AI bucket, families the clips by name (:mod:`util.version_groups`)
plus the pairs ``config.NONAI_VERSION_OVERRIDES`` declares, folds together the
differently named copies whose pictures show them to be one video
(:mod:`util.same_footage`), and writes each a sidecar — mirrored under ``METADATA_DIR`` exactly like the AI tree — recording
its family id and whether it is a processed variant.

Being the source of truth means it rewrites ``version.group`` on every run, so
editing a sidecar by hand does not hold: an override is the way to correct one.

New clips get grouped on the next run; sidecars for clips that have since moved
or been deleted are pruned, so the metadata tree stays a faithful record of the
library Evolver knows about.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import config
from util import same_footage, sidecar
from util.media_files import file_size, is_finalized_video_file
from util.nonai_library import buckets
from util.variants import is_processed_stem, strip_processing_suffixes
from util.version_groups import group_ids
from util.video_type import duration_of

log = logging.getLogger(__name__)

# Measuring a video's pictures costs a few seconds of decoding, and a folder of
# same-length videos arrives all at once; the rest wait for the next run.
MEASURED_PER_RUN = 8

Fingerprint = Callable[[Path, float], list[str] | None]


@dataclass
class NonAiGroupResult:
    grouped: int = 0
    families: int = 0
    written: int = 0
    pruned: int = 0
    joined: int = 0
    measured: int = 0


def run(*, fingerprint: Fingerprint = same_footage.fingerprint) -> NonAiGroupResult:
    """Group every non-AI clip and record its family in a mirrored sidecar."""
    log.info("=== Stage: group non-AI versions ===")
    result = NonAiGroupResult()
    measure = _Allowance(fingerprint, MEASURED_PER_RUN)
    expected: set[Path] = set()

    for bucket in buckets():
        videos = [
            video
            for video in sorted(bucket.rglob("*"))
            if is_finalized_video_file(video)
        ]
        if not videos:
            continue
        named = group_ids([video.stem for video in videos], config.NONAI_VERSION_OVERRIDES)
        existing_by_video = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
        ids = _joined_by_pictures(videos, existing_by_video, named, measure)
        # A `clip` object (compilation, source, performer) describes one carved
        # scene, and its re-encodes are the same scene — so an upscaled variant
        # inherits it and stays a navigable short. Keying that on the *family*
        # would be too broad: a family is name-derived, so a full scene the user
        # already owned can share it with a clip carved from the same movie, and
        # would wrongly be marked a clip. Key on the stripped stem instead, which
        # only ever matches genuine re-encodes of that one file.
        clip_by_origin: dict[str, dict] = {}
        for video in videos:
            clip = existing_by_video[video].get("clip")
            if isinstance(clip, dict):
                clip_by_origin.setdefault(strip_processing_suffixes(video.stem), clip)
        for video in videos:
            version = {
                "group": ids[video.stem],
                "processed": is_processed_stem(video.stem),
            }
            origin_clip = clip_by_origin.get(strip_processing_suffixes(video.stem))

            def record_the_family(
                payload: dict, version=version, origin_clip=origin_clip,
            ) -> dict | None:
                grouped = dict(payload)
                grouped["version"] = version
                if origin_clip is not None:
                    grouped["clip"] = origin_clip
                return grouped if grouped != payload else None

            path = sidecar.sidecar_path(video)
            expected.add(path)
            if sidecar.update(path, record_the_family) is not None:
                result.written += 1
        result.grouped += len(videos)
        result.families += len(set(ids.values()))
        result.joined += len(set(named.values())) - len(set(ids.values()))

    result.pruned = _prune_orphans(expected)
    result.measured = measure.taken
    log.info(
        "Non-AI grouping: %d clip(s) in %d family(ies), %d of them joined by their "
        "pictures (%d measured); wrote %d, pruned %d sidecar(s).",
        result.grouped, result.families, result.joined, result.measured,
        result.written, result.pruned,
    )
    return result


class _Allowance:
    def __init__(self, fingerprint: Fingerprint, allowance: int) -> None:
        self._fingerprint = fingerprint
        self._left = allowance
        self.taken = 0

    def __call__(self, video: Path, seconds: float) -> list[str] | None:
        if self._left <= 0:
            return None
        self._left -= 1
        self.taken += 1
        return self._fingerprint(video, seconds)


def _joined_by_pictures(
    videos: list[Path], payloads: dict[Path, dict], ids: dict[str, str],
    fingerprint: Fingerprint,
) -> dict[str, str]:
    families: dict[str, list[Path]] = {}
    for video in videos:
        if not isinstance(payloads[video].get("clip"), dict):
            families.setdefault(ids[video.stem], []).append(video)
    lengths = {family: _running_time(files, payloads) for family, files in families.items()}
    pairs = [
        (a, b) for a, b in combinations(sorted(families), 2)
        if lengths[a] is not None and lengths[b] is not None
        and same_footage.same_length(lengths[a], lengths[b])
    ]
    prints = {family: _family_fingerprint(families[family], payloads, lengths[family], fingerprint)
              for family in {family for pair in pairs for family in pair}}
    joined = [(a, b) for a, b in pairs
              if prints[a] and prints[b] and same_footage.same_footage(prints[a], prints[b])]
    return same_footage.join(ids, joined)


def _running_time(files: list[Path], payloads: dict[Path, dict]) -> float | None:
    return next((seconds for video in files
                 if (seconds := duration_of(payloads[video])) is not None), None)


def _family_fingerprint(
    files: list[Path], payloads: dict[Path, dict], seconds: float, fingerprint: Fingerprint,
) -> list[str] | None:
    for video in files:
        kept = same_footage.fingerprint_of(payloads[video])
        if kept is not None:
            return kept
    cheapest = min(files, key=lambda video: (file_size(video), str(video)))
    measured = fingerprint(cheapest, seconds)
    if measured is not None:
        sidecar.update(sidecar.sidecar_path(cheapest),
                       lambda payload: same_footage.fingerprinted(payload, measured))
    return measured


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
