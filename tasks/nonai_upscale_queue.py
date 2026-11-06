from __future__ import annotations

from pathlib import Path

from tasks import nonai_encode
from tasks.nonai_files import StageFiles
from tasks.nonai_queue import collect_queued_videos, listed_videos, relpath
from tasks.nonai_titles import TITLE_FIELD
from util import nonai_job, sidecar, video_kind
from util.upscale_queue import (
    ASKED_FOR,
    FINISHING,
    NEXT,
    PAUSED,
    STARTING,
    UPSCALING,
    Entry,
    Head,
    UpscaleQueue,
)


def current() -> UpscaleQueue:
    files = StageFiles.configured()
    pinned = set(listed_videos(files.pin_list))
    entries = [_entry(queued_video.path, pinned) for queued_video in collect_queued_videos(
        skip_list=files.skip_list, pin_list=files.pin_list,
        watch_stats_file=files.watch_stats)]
    first, head = _first(files, entries, pinned)
    if first is None:
        return UpscaleQueue(rows=tuple(entries), head=Head(NEXT) if entries else None)
    rest = tuple(entry for entry in entries if entry.video != first.video)
    return UpscaleQueue(rows=(first, *rest), head=head)


def _first(files: StageFiles, entries: list[Entry],
           pinned: set[str]) -> tuple[Entry | None, Head | None]:
    job = nonai_job.load_job(files.job)
    request = nonai_job.load_request(files.request)
    if job is not None:
        entry = _known(entries, relpath(job.source)) or _entry(job.source, pinned)
        if job.is_running():
            return entry, Head(_state(job), nonai_encode.percent_encoded(job))
        if request is None:
            return entry, Head(FINISHING)
    if request is not None:
        entry = _known(entries, request.video) or Entry(
            request.video, Path(request.video).stem, None, request.video in pinned)
        return entry, Head(STARTING, held_back=request.held_back)
    return None, None


def _state(job: nonai_job.Job) -> str:
    if job.on_request:
        return ASKED_FOR
    return PAUSED if job.suspended else UPSCALING


def _known(entries: list[Entry], video: str) -> Entry | None:
    return next((entry for entry in entries if entry.video == video), None)


def _entry(video: Path, pinned: set[str]) -> Entry:
    payload = sidecar.read(sidecar.sidecar_path(video))
    return Entry(
        video=relpath(video),
        name=str(payload.get(TITLE_FIELD) or video.stem),
        seconds=video_kind.duration_of(payload),
        pinned=relpath(video) in pinned,
    )
