"""Where a video went, for references that still point at where it was."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import config
from util import ffprobe
from util.media_files import file_size, is_finalized_video_file, library_videos
from util.nonai_library import bucket_of
from util.variants import strip_processing_suffixes
from util.weird_piles import weird_piles


def build_index() -> dict[str, list[Path]]:
    """Index every video under the search root by lowercased filename.

    Videos sitting in a condemned pile are left out: the purge stage deletes
    them and their sources, so pointing a reference at one only re-breaks it.
    """
    index: dict[str, list[Path]] = defaultdict(list)
    root = config.VIDEO_SEARCH_ROOT
    if not root.is_dir():
        return index
    piles = weird_piles()
    for video_path in library_videos(root):
        if any(video_path.is_relative_to(pile.directory) for pile in piles):
            continue
        index[video_path.name.lower()].append(video_path)
    return index


def relocate(was_at: Path, index: dict[str, list[Path]]) -> Path | None:
    """The one video now carrying that filename, or None if none or several do."""
    matches = index.get(was_at.name.lower(), [])
    return matches[0] if len(matches) == 1 else None


def another_version_of(was_at: Path, index: dict[str, list[Path]]) -> Path | None:
    """The smallest other version of that video still in its bucket, if any.

    The upscale that replaces a non-AI original is published into the same
    bucket under the original's name plus processing suffixes, and the original
    leaves -- so this is where a video that was upscaled away is found.
    """
    bucket = bucket_of(was_at)
    if bucket is None:
        return None
    original = strip_processing_suffixes(was_at.stem).casefold()
    versions = [
        video for videos in index.values() for video in videos
        if strip_processing_suffixes(video.stem).casefold() == original
        and bucket_of(video) == bucket
    ]
    return min(versions, key=lambda video: (file_size(video), str(video))) if versions else None


def renamed_in_place(was_at: Path, fingerprint: tuple[float, int]) -> Path | None:
    """The video that took this one's name in the same folder, by frame fingerprint.

    A rename leaves nothing of the old name to match on, so the only handle left
    is the footage itself — and a reference that records fps and a frame count
    is holding exactly that. The search stays in the one folder the reference
    named, since renaming a file in place is what this covers and probing the
    whole library on the off chance is not worth the minutes it costs.
    """
    matches = [
        candidate
        for candidate in sorted(was_at.parent.glob("*"))
        if is_finalized_video_file(candidate)
        and _same_footage(ffprobe.frame_fingerprint(candidate), fingerprint)
    ]
    return matches[0] if len(matches) == 1 else None


def _same_footage(candidate: tuple[float, int] | None, wanted: tuple[float, int]) -> bool:
    if candidate is None:
        return False
    return candidate[1] == wanted[1] and math.isclose(candidate[0], wanted[0], rel_tol=1e-6)
