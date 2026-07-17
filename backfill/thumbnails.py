"""Example thumbnails for the backfill window's clickable tiles.

Each act tile can show a still from a clip the library already labels with that act,
so the grid reads as a gallery you recognize at a glance rather than a wall of words.
The clips already exist — every source the scrape stage or an earlier backfill run
tagged is a candidate — so a thumbnail is one extracted frame, cached under
``config.BACKFILL_THUMBNAIL_DIR`` and reused on every later open.

The work is off the GUI thread: scanning the whole library and shelling out to ffmpeg
per act is seconds of latency, so :class:`ThumbnailLoader` runs it in a background
thread and emits each thumbnail as it lands. The pure pieces —
:func:`build_thumbnails`, :func:`example_clips`, :func:`thumbnail_cache_path` — take
their effects as arguments or touch only the filesystem, so they are tested without
ffmpeg or Qt; the loader is the thin thread around them, mirroring VoiceListener.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

import config
from backfill.queue import iter_library_videos
from util.ffprobe import duration_seconds
from util.sidecar import action_of, read, sidecar_path

log = logging.getLogger(__name__)

_THUMBNAIL_HEIGHT = 96
# Sample the frame from a little way in, past a clip's title card or fade-in.
_SAMPLE_FRACTION = 0.4


def example_clips() -> dict[str, Path]:
    """One representative labeled clip per act, as ``action -> clip``.

    Every source is fair game — including the scraped ones the work queue hides,
    since a clip already tagged ``Side Gamma`` is exactly the example that tile
    wants. The first clip found for an act (in the library's stable order) wins.
    """
    examples: dict[str, Path] = {}
    for _source, video in iter_library_videos():
        action = action_of(read(sidecar_path(video)))
        if action and action not in examples:
            examples[action] = video
    return examples


def thumbnail_cache_path(action: str) -> Path:
    """Where *action*'s cached thumbnail lives — one stable file name per act."""
    slug = re.sub(r"[^a-z0-9]+", "_", action.lower()).strip("_") or "unnamed"
    return config.BACKFILL_THUMBNAIL_DIR / f"{slug}.jpg"


def extract_frame(
    clip: Path, dest: Path, *, at_fraction: float = _SAMPLE_FRACTION, height: int = _THUMBNAIL_HEIGHT
) -> bool:
    """Write one downscaled frame of *clip* to *dest*; True when it lands.

    Seeks to *at_fraction* of the clip's duration (0 when the duration is unknown)
    and scales to *height*, keeping the aspect ratio. Uses the same Topaz ffmpeg
    and console-suppressed invocation the rest of the pipeline does.
    """
    duration = duration_seconds(clip)
    timestamp = duration * at_fraction if duration else 0.0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                str(config.FFMPEG),
                "-nostdin",
                "-ss", f"{timestamp:.3f}",
                "-i", str(clip),
                "-frames:v", "1",
                "-vf", f"scale=-2:{height}",
                "-y", str(dest),
            ],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        log.exception("Could not run ffmpeg to thumbnail %s", clip)
        return False
    return result.returncode == 0 and dest.is_file()


def build_thumbnails(
    examples: Mapping[str, Path],
    extract: Callable[[Path, Path], bool],
    cache_path_for: Callable[[str], Path],
):
    """Yield ``(action, thumbnail path)`` for each example that has, or gets, one.

    A cached frame is reused; otherwise one is extracted and cached. An act whose
    extraction fails is skipped, so its tile simply stays text-only.
    """
    for action, clip in examples.items():
        dest = cache_path_for(action)
        if dest.is_file() or extract(clip, dest):
            yield action, dest


class ThumbnailLoader(QObject):
    """Builds the tiles' thumbnails off the GUI thread, emitting each as it lands."""

    ready = pyqtSignal(str, str)  # action, thumbnail path

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            for action, path in build_thumbnails(example_clips(), extract_frame, thumbnail_cache_path):
                if self._stop.is_set():
                    return
                self.ready.emit(action, str(path))
        except Exception:
            log.exception("Thumbnail loader crashed")
