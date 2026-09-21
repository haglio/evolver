"""The upscale queue as the window shows it: one list, the video in flight on top.

The stage's own view of the same queue is a count and a name in a log line.
This is the rest of it — every video in the order the stage would take them,
called what the library calls them, with whatever the machine is on (or was
asked to start) lifted to the first row and what is happening to it said in a
word (:mod:`util.upscale_lineup`).

Read on the GUI thread, without the lock the stage takes: every file it reads
is written whole, so the worst a badly timed read sees is the state a moment
ago, and the window reads again a few seconds later.
"""

from __future__ import annotations

from pathlib import Path

from tasks import nonai_encode
from tasks.nonai_queue import collect_candidates, listed_videos, relpath
from tasks.nonai_titles import TITLE_FIELD
from tasks.nonai_upscale import StageFiles
from util import nonai_job, processes, sidecar, video_type
from util.upscale_lineup import (
    ASKED_FOR,
    FINISHING,
    NEXT,
    PAUSED,
    STARTING,
    UPSCALING,
    Entry,
    Head,
    Lineup,
)


def current() -> Lineup:
    files = StageFiles.configured()
    pinned = set(listed_videos(files.pin_list))
    entries = [_entry(candidate.path, pinned) for candidate in collect_candidates(
        skip_list=files.skip_list, pin_list=files.pin_list,
        watch_stats_file=files.watch_stats)]
    first, head = _first(files, entries, pinned)
    if first is None:
        return Lineup(rows=tuple(entries), head=Head(NEXT) if entries else None)
    rest = tuple(entry for entry in entries if entry.video != first.video)
    return Lineup(rows=(first, *rest), head=head)


def _first(files: StageFiles, entries: list[Entry],
           pinned: set[str]) -> tuple[Entry | None, Head | None]:
    """The video the machine is on or was asked to start, and what it is doing."""
    job = nonai_job.load_job(files.job)
    request = nonai_job.load_request(files.request)
    if job is not None and job.get("source"):
        source = Path(job["source"])
        entry = _known(entries, relpath(source)) or _entry(source, pinned)
        if job.get("pid") and processes.is_running(job["pid"]):
            return entry, Head(_state(job), nonai_encode.percent_encoded(job))
        if request is None:
            return entry, Head(FINISHING)
    if request is not None:
        entry = _known(entries, request.video) or Entry(
            request.video, Path(request.video).stem, None, request.video in pinned)
        return entry, Head(STARTING, held_back=request.held_back)
    return None, None


def _state(job: dict) -> str:
    if job.get("on_request"):
        return ASKED_FOR
    return PAUSED if job.get("suspended") else UPSCALING


def _known(entries: list[Entry], video: str) -> Entry | None:
    return next((entry for entry in entries if entry.video == video), None)


def _entry(video: Path, pinned: set[str]) -> Entry:
    payload = sidecar.read(sidecar.sidecar_path(video))
    return Entry(
        video=relpath(video),
        name=str(payload.get(TITLE_FIELD) or video.stem),
        seconds=video_type.duration_of(payload),
        pinned=relpath(video) in pinned,
    )
