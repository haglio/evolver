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
