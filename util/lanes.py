"""Every video the library holds, lane by lane."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from util.media_files import is_finalized_video_file, iter_finalized_videos
from util.sidecar import upscaled_video_path


@dataclass(frozen=True)
class AiClip:
    video: Path
    source: str
    orientation: str

    @property
    def upscale(self) -> Path:
        return upscaled_video_path(self.source, self.orientation, self.video.stem)


def ai_clips() -> Iterator[AiClip]:
    if not config.SORTED_DIR.is_dir():
        return
    for source_dir in sorted(p for p in config.SORTED_DIR.iterdir() if p.is_dir()):
        for orient_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            for video in sorted(iter_finalized_videos(orient_dir, config.VIDEO_EXTENSIONS)):
                yield AiClip(video, source_dir.name, orient_dir.name)


def genau_clips() -> Iterator[Path]:
    if not config.GENAU_CLIPS_DIR.is_dir():
        return
    for video in sorted(config.GENAU_CLIPS_DIR.iterdir()):
        if is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
            yield video


def non_ai_videos() -> list[Path]:
    if not config.NON_AI_DIR.is_dir():
        return []
    return sorted(iter_finalized_videos(config.NON_AI_DIR, config.VIDEO_EXTENSIONS))
