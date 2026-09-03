"""Which non-AI clip the upscale stage encodes next, and in what order.

Candidates come from the buckets' triage folders (``0 unsorted``, ``1 could
use work``), most-wanted first: a pin in the priority manifest beats everything
and also re-queues a video whose only processed variant came from an older
recipe, then an explicit ``1`` flag, then Fun Time's watch score, then clips
with a funscript — the only per-video engagement signal the non_AI library has
of its own.

The three files this reads are arguments rather than ambient config: the two
hand-edited manifests are the user's, the watch stats are a sibling app's, and
naming them at the call makes it visible that listing candidates opens three
files besides walking the tree. What stays ambient is the library itself —
where the non-AI root is, and what counts as a video — which is one repo-wide
answer that no caller varies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import funscript
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets, stage_dirs
from util.variants import is_processed_stem, strip_processing_suffixes

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    path: Path
    bucket: Path
    triage_digit: int
    has_funscript: bool
    watch_score: float


def collect_candidates(*, skip_manifest: Path, pin_manifest: Path,
                       watch_stats_file: Path) -> list[Candidate]:
    """Unprocessed triage-folder videos, most-wanted first."""
    candidates: list[Candidate] = []
    skipped = set(manifest_entries(skip_manifest))
    pinned = manifest_entries(pin_manifest)
    watch_scores = _watch_scores(watch_stats_file)
    for bucket in buckets():
        processed_stems = _processed_stems(bucket)
        for triage_digit, triage_dir in stage_dirs(bucket, digits=(0, 1)):
            for scan_dir in _upscale_ready_dirs(triage_dir):
                for video in sorted(scan_dir.iterdir()):
                    if not is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
                        continue
                    rel = relpath(video)
                    if is_processed_stem(video.stem):
                        continue
                    # A variant of this video already existing normally means
                    # there is nothing to do. A pin overrides that: the variant
                    # is an older recipe, and the redo is the whole point.
                    if video.stem in processed_stems and rel not in pinned:
                        continue
                    if rel in skipped:
                        continue
                    candidates.append(Candidate(
                        video, bucket, triage_digit, _has_funscript(video),
                        watch_scores.get(str(video).strip().lower(), 0.0),
                    ))
    candidates.sort(key=lambda c: (
        _pin_rank(pinned, c.path),
        c.triage_digit != 1, -c.watch_score, not c.has_funscript, str(c.path).lower(),
    ))
    return candidates


def relpath(video: Path) -> str:
    """*video*'s path within the non-AI library — the key everything here uses.

    Both manifests are written in it by hand, the attempt counter is keyed by
    it, and it is what the stage reports and logs, so one spelling has to serve
    all four.
    """
    return video.relative_to(config.NON_AI_DIR).as_posix()


def add_to_skip_manifest(manifest: Path, source: Path, reason: str) -> None:
    log.warning("Skipping %s permanently: %s", source, reason)
    with open(manifest, "a", encoding="utf-8") as handle:
        handle.write(f"{relpath(source)}\t{reason}\n")


def manifest_entries(path: Path) -> list[str]:
    """A hand-edited manifest's relative paths, in file order.

    One path per line; anything past a tab is the user's own note about why.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.split("\t", 1)[0].strip() for line in lines if line.strip()]


def _upscale_ready_dirs(triage_dir: Path) -> list[Path]:
    """*triage_dir* plus the sub-stages of it whose clips need only the encode.

    A triage dir can split into numbered sub-stages. The first is manual
    pre-work — "1_originals_needing_trimming" still wants a human with a
    trimmer, so an unattended multi-hour encode would bake in the untrimmed
    footage. The later ones say in their own names that trimming is settled and
    upscaling is all that's left, so their clips queue like direct children do.
    """
    return [triage_dir] + [d for _, d in stage_dirs(triage_dir, digits=(2, 3))]


def _processed_stems(bucket: Path) -> set[str]:
    """Original stems that already have a processed variant somewhere in *bucket*."""
    stems = set()
    for video in bucket.rglob("*"):
        if is_finalized_video_file(video, config.VIDEO_EXTENSIONS) and is_processed_stem(video.stem):
            stems.add(strip_processing_suffixes(video.stem))
    return stems


def _watch_scores(path: Path) -> dict[str, float]:
    """Fun Time's per-video watch score, keyed by its normalized path.

    Mirrors the breeding score its playlist weighting uses: completions plus
    three per lock, minus skips. Empty until Fun Time starts tracking primary
    (Nau) plays; satellite entries all point at the AI outbox and simply never
    match a non-AI candidate.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: entry.get("completions", 0) + 3 * entry.get("locks", 0) - entry.get("skips", 0)
        for key, entry in payload.items()
        if isinstance(entry, dict)
    }


def _has_funscript(video: Path) -> bool:
    return funscript.script_path_for_video(video).is_file()


def _pin_rank(pinned: list[str], video: Path) -> int:
    """Where *video* sits in the pin list — past the end when it is not pinned."""
    try:
        return pinned.index(relpath(video))
    except ValueError:
        return len(pinned)
