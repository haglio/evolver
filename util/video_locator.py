"""Where a video went, for references that still point at where it was."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import config
from util.media_files import iter_finalized_videos


def build_index() -> dict[str, list[Path]]:
    """Index every video under the search root by lowercased filename.

    Videos sitting in ``kinda_weird`` are left out: the purge stage deletes them
    and their sources, so pointing a reference at one only re-breaks it.
    """
    index: dict[str, list[Path]] = defaultdict(list)
    root = config.VIDEO_SEARCH_ROOT
    if not root.is_dir():
        return index
    doomed = tuple(config.active_weird_dirs())
    for video_path in iter_finalized_videos(root, config.VIDEO_EXTENSIONS):
        if any(video_path.is_relative_to(weird_dir) for weird_dir in doomed):
            continue
        index[video_path.name.lower()].append(video_path)
    return index


def relocate(was_at: Path, index: dict[str, list[Path]]) -> Path | None:
    """The one video now carrying that filename, or None if none or several do."""
    matches = index.get(was_at.name.lower(), [])
    return matches[0] if len(matches) == 1 else None
