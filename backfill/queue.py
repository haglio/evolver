from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes, orientation, sidecar
from util.media_files import library_videos
from util.sidecar import action_of, sidecar_path, wrong_action_of
from util.versions import sorted_stem_of

_ORIENTATIONS = (orientation.PORTRAIT, orientation.LANDSCAPE)


def scraped_sources() -> frozenset[str]:
    return frozenset({config.PROVIDER_SOURCE, lanes.ORIGENERATOR_SOURCE})


def iter_library_videos() -> Iterator[tuple[str, Path]]:
    for orient in _ORIENTATIONS:
        orient_dir = config.OUT_UPSCALED_DIR / orient
        if not orient_dir.is_dir():
            continue
        for source_dir in sorted(p for p in orient_dir.iterdir() if p.is_dir()):
            for video in sorted(library_videos(source_dir)):
                yield source_dir.name, video


@dataclass(frozen=True)
class ScannedVideo:
    source: str
    path: Path
    action: str
    wrong_action: str
    video_id: str


def library_scan() -> list[ScannedVideo]:
    return [
        ScannedVideo(
            source=source,
            path=video,
            action=action_of(payload),
            wrong_action=wrong_action_of(payload),
            video_id=sorted_stem_of(video.stem),
        )
        for source, video in iter_library_videos()
        if (payload := sidecar.read(sidecar_path(video))) is not None
    ]


def unlabeled_videos(scan: list[ScannedVideo] | None = None) -> list[Path]:
    scan = library_scan() if scan is None else scan
    scraped = scraped_sources()
    rejected: list[Path] = []
    never_labeled: list[Path] = []
    for video in scan:
        if video.action:
            continue
        if video.wrong_action:
            rejected.append(video.path)
        elif video.source not in scraped:
            never_labeled.append(video.path)
    return rejected + never_labeled


class BackfillQueue:
    def __init__(self, videos: list[Path]) -> None:
        self._pending = deque(videos)

    @property
    def remaining(self) -> int:
        return len(self._pending)

    @property
    def current(self) -> Path | None:
        return self._pending[0] if self._pending else None

    def resolve(self) -> None:
        if self._pending:
            self._pending.popleft()

    def defer(self) -> None:
        if self._pending:
            self._pending.rotate(-1)

    def restore(self, video: Path) -> None:
        self._pending.appendleft(video)

    def undefer(self) -> None:
        if self._pending:
            self._pending.rotate(1)
