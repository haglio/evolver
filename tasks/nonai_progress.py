from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app_support.video_names import strip_processing_suffixes

from util import sidecar, video_kind
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets
from util.versions import is_processed_stem


@dataclass(frozen=True)
class Progress:
    done_seconds: float = 0.0
    remaining_seconds: float = 0.0
    unmeasured: int = 0

    @property
    def percent(self) -> int | None:
        total = self.done_seconds + self.remaining_seconds
        return None if total <= 0 else round(self.done_seconds / total * 100)


def so_far(queued: Iterable[Path]) -> Progress:
    done_seconds, unmeasured = _total(_upscaled().values())
    remaining_seconds, still_unmeasured = _total(_recorded_duration(video)
                                                 for video in queued)
    return Progress(done_seconds, remaining_seconds, unmeasured + still_unmeasured)


def _total(durations: Iterable[float | None]) -> tuple[float, int]:
    total, unmeasured = 0.0, 0
    for seconds in durations:
        if seconds is None:
            unmeasured += 1
        else:
            total += seconds
    return total, unmeasured


def _upscaled() -> dict[str, float | None]:
    found: dict[str, float | None] = {}
    for bucket in buckets():
        for video in sorted(bucket.rglob("*")):
            if not is_finalized_video_file(video):
                continue
            if not is_processed_stem(video.stem):
                continue
            original = strip_processing_suffixes(video.stem)
            if found.get(original) is None:
                found[original] = _recorded_duration(video)
    return found


def _recorded_duration(video: Path) -> float | None:
    return video_kind.duration_of(sidecar.read(sidecar.sidecar_path(video)))
