from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app_support.video_kind import classify, free_kind

import config
from util import lanes, orientation, sidecar, video_kind
from util.ffprobe import duration_seconds, orientation_of
from util.library_records import CLIP_BLOCK
from util.stage_result import StageResult

log = logging.getLogger(__name__)

_NEITHER_PORTRAIT_NOR_LANDSCAPE = None


@dataclass(frozen=True)
class _Listed:
    video: Path
    sidecar: Path
    payload: dict
    genau: bool = False
    clip: bool = False
    orientation: str | None = ""
    on_the_cloud_drive: bool = False


@dataclass
class _Measurements:
    left: int
    left_on_the_cloud_drive: int

    def spent_on(self, listed: _Listed) -> bool:
        if self.left <= 0 or (listed.on_the_cloud_drive and self.left_on_the_cloud_drive <= 0):
            return False
        self.left -= 1
        if listed.on_the_cloud_drive:
            self.left_on_the_cloud_drive -= 1
        return True

    def none_more_from_the_cloud_drive(self) -> None:
        self.left_on_the_cloud_drive = 0


@dataclass
class VideoKindsResult(StageResult):
    recorded: int = 0
    already: int = 0
    skipped: int = 0
    deferred: int = 0


def run(probe=duration_seconds, orientation_probe=orientation_of) -> VideoKindsResult:
    log.info("=== Stage: record video kinds ===")
    result = VideoKindsResult()
    measurements = _Measurements(config.VIDEO_KIND_PROBES_PER_RUN, config.CLOUD_DRIVE_PROBES_PER_RUN)
    for listed in _library_videos():
        free = free_kind(genau=listed.genau, excerpt=listed.clip)
        seconds = video_kind.duration_of(listed.payload)
        unmeasurable = False
        if seconds is None and measurements.spent_on(listed):
            seconds = probe(listed.video)
            unmeasurable = seconds is None
            if unmeasurable:
                log.info("Could not measure %s; leaving it for the next run", listed.video)
                if listed.on_the_cloud_drive:
                    measurements.none_more_from_the_cloud_drive()
        if seconds is None and not free:
            if unmeasurable:
                result.skipped += 1
            else:
                result.deferred += 1
            continue

        oriented = listed.orientation is not _NEITHER_PORTRAIT_NOR_LANDSCAPE
        orient = (listed.orientation or video_kind.orientation_of(listed.payload)) if oriented else ""
        if oriented and not orient and measurements.spent_on(listed):
            orient = _orientation_measured(listed.video, orientation_probe)

        def record_what_is_known(
            current: dict, genau=listed.genau, clip=listed.clip, seconds=seconds,
            orient=orient,
        ) -> dict | None:
            written = video_kind.stamped(
                current, classify(genau=genau, excerpt=clip, duration_seconds=seconds))
            if seconds is not None:
                written = video_kind.timed(written, seconds)
            if orient:
                written = video_kind.oriented(written, orient)
            return written if written != current else None

        if sidecar.update(listed.sidecar, record_what_is_known) is not None:
            result.recorded += 1
        elif seconds is None or (oriented and not orient):
            result.deferred += 1
        else:
            result.already += 1
    log.info(
        "Video kinds: recorded %d, already known %d, skipped %d, deferred %d.",
        result.recorded, result.already, result.skipped, result.deferred,
    )
    return result


def _orientation_measured(video: Path, orientation_probe) -> str:
    measured = orientation_probe(video)
    if measured == orientation.UNKNOWN:
        log.info("Could not tell whether %s is portrait or landscape; leaving it "
                 "for the next run", video)
        return ""
    return measured


def _library_videos():
    yield from _genau_flicks()
    yield from _ai_videos()
    yield from _non_ai_videos()
    yield from _vr_videos()


def _genau_flicks():
    for video in lanes.genau_flicks():
        path = sidecar.sidecar_path(video)
        yield _Listed(video, path, sidecar.read(path), genau=True)


def _ai_videos():
    for clip in lanes.ai_videos():
        path = sidecar.sidecar_path(clip.upscale)
        filed_under = clip.orientation if clip.orientation in orientation.SORTED else ""
        yield _Listed(clip.video, path, sidecar.read(path),
                      genau=clip.source == config.GENAU_SOURCE, orientation=filed_under)


def _non_ai_videos():
    videos = lanes.non_ai_videos()
    payloads = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
    carved = {video for video, payload in payloads.items() if _was_carved(video, payload)}
    cuts = _cut_folders(
        [_below_the_library(video) for video in videos if video in carved],
        [_below_the_library(video) for video in videos if video not in carved],
    )
    for video in videos:
        clip = video in carved or _in_a_cut_folder(_below_the_library(video), cuts)
        yield _Listed(video, sidecar.sidecar_path(video), payloads[video], clip=clip)


def _vr_videos():
    for vr in lanes.vr_videos():
        path = sidecar.sidecar_path(vr.in_library)
        yield _Listed(vr.video, path, sidecar.read(path),
                      orientation=_NEITHER_PORTRAIT_NOR_LANDSCAPE, on_the_cloud_drive=True)


def _was_carved(video: Path, payload: dict) -> bool:
    return isinstance(payload.get(CLIP_BLOCK), dict) or _in_a_clip_folder(video)


def _below_the_library(video: Path) -> tuple[str, ...]:
    return video.relative_to(config.NON_AI_DIR).parts[:-1]


def _in_a_clip_folder(video: Path) -> bool:
    relative = video.relative_to(config.VIDEO_LIBRARY_DIR).as_posix()
    return any(relative.startswith(folder) for folder in config.CLIP_FOLDERS)


def _in_a_cut_folder(folders: tuple[str, ...], cuts: dict[str, str]) -> bool:
    return len(folders) > 1 and cuts.get(folders[0]) == folders[1]


def _cut_folders(
    carved: list[tuple[str, ...]], others: list[tuple[str, ...]]
) -> dict[str, str]:
    def by_batch(folders: list[tuple[str, ...]]) -> dict[str, list[tuple[str, ...]]]:
        grouped: dict[str, list[tuple[str, ...]]] = {}
        for path in folders:
            if path:
                grouped.setdefault(path[0], []).append(path)
        return grouped

    cuts, rest = by_batch(carved), by_batch(others)
    found = {}
    for batch, folders in cuts.items():
        mine = _own_second(folders, rest.get(batch, []))
        if mine:
            found[batch] = mine
    return found


def _own_second(band: list[tuple[str, ...]], mate: list[tuple[str, ...]]) -> str:
    mine, theirs = _dominant_second(band), _dominant_second(mate)
    if not mine or not theirs or mine == theirs:
        return ""
    return mine if _holds_mostly(mine, band, mate) and _holds_mostly(theirs, mate, band) else ""


def _holds_mostly(second: str, band: list[tuple[str, ...]], mate: list[tuple[str, ...]]) -> bool:
    return _count_under(second, band) > _count_under(second, mate)


def _count_under(second: str, folders: list[tuple[str, ...]]) -> int:
    return sum(1 for path in folders if len(path) > 1 and path[1] == second)


def _dominant_second(folders: list[tuple[str, ...]]) -> str:
    seconds = Counter(path[1] for path in folders if len(path) > 1)
    if not seconds:
        return ""
    name, count = seconds.most_common(1)[0]
    return name if count * 2 > sum(seconds.values()) else ""
