"""Example thumbnails for the backfill window's clickable buttons.

Each act button shows a still from a video that illustrates that act, so the grid reads
as a gallery you recognize at a glance rather than a wall of words. A thumbnail is one
extracted frame, cached under ``config.BACKFILL_THUMBNAIL_DIR`` and reused on every
later open, so the window only ever loads ready files — it never extracts on open.

A button's example comes from one of two places, curated first:

* ``config.CURATED_EXAMPLES`` pins a specific video to a button by id. This is how the acts
  the library never tags in a camera-scoped form get a thumbnail — a side gamma, say
  — and how a video mistagged (or tagged for a different act than it best shows)
  is still put to use.
* otherwise the first library video whose ``video.action`` matches the button, taken from
  a single scan. A compound tag like ``Side Epsilon, Alpha`` counts as each of its
  comma-separated parts, so it can illustrate either button.

The pure pieces take their effects as arguments or touch only the filesystem, so they
are tested without ffmpeg or Qt.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from backfill.queue import ScannedVideo
from backfill.vocabulary import Vocabulary
from util.ffprobe import duration_seconds

log = logging.getLogger(__name__)

_THUMBNAIL_HEIGHT = 96
_SAMPLE_FRACTION = 0.4

def _button_labels(vocabulary: Vocabulary) -> list[str]:
    return [command.label for row in vocabulary.scoped_grid() for command in row]


def _lookups(scan: list[ScannedVideo]) -> tuple[dict[str, Path], dict[str, Path]]:
    by_action: dict[str, Path] = {}
    by_id: dict[str, Path] = {}
    for video in scan:
        by_id.setdefault(video.video_id, video.path)
        for listed in video.action.split(","):
            part = listed.strip().lower()
            if part:
                by_action.setdefault(part, video.path)
    return by_action, by_id


def example_videos(vocabulary: Vocabulary, scan: list[ScannedVideo]) -> dict[str, Path]:
    by_action, by_id = _lookups(scan)
    examples: dict[str, Path] = {}
    for label in _button_labels(vocabulary):
        video = (by_id.get(config.CURATED_EXAMPLES.get(label, ""))
                or by_action.get(label.lower()))
        if video is not None:
            examples[label] = video
    return examples


def thumbnail_cache_path(label: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "unnamed"
    return config.BACKFILL_THUMBNAIL_DIR / f"{slug}.jpg"


def extract_frame(video: Path, dest: Path, *, at_fraction: float = _SAMPLE_FRACTION) -> bool:
    """Write one downscaled frame of *video* to *dest*; True when it lands.

    Seeks to *at_fraction* of the video's duration (0 when the duration is unknown)
    and scales to ``_THUMBNAIL_HEIGHT``, keeping the aspect ratio. Uses the same
    Topaz ffmpeg and console-suppressed invocation the rest of the pipeline does.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        duration = duration_seconds(video)
        timestamp = duration * at_fraction if duration else 0.0
        result = subprocess.run(
            [
                str(config.FFMPEG),
                "-nostdin",
                "-ss", f"{timestamp:.3f}",
                "-i", str(video),
                "-frames:v", "1",
                "-vf", f"scale=-2:{_THUMBNAIL_HEIGHT}",
                "-y", str(dest),
            ],
            capture_output=True,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except OSError:
        log.exception("Could not build a thumbnail for %s", video)
        return False
    return result.returncode == 0 and dest.is_file()


def build_thumbnails(
    examples: Mapping[str, Path],
    extract: Callable[[Path, Path], bool],
    cache_path_for: Callable[[str], Path],
):
    for label, video in examples.items():
        dest = cache_path_for(label)
        if dest.is_file() or extract(video, dest):
            yield label, dest
