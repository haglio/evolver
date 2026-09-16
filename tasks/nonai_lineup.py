"""The upscale queue as the window shows it: what is being upscaled, and what is next.

The stage's own view of the same queue is a count and a name in a log line.
This is the rest of it — every video in the order the stage would take them,
called what the library calls them, with the one in flight lifted out of the
list and what is happening to it said in a word (:mod:`util.upscale_lineup`).

Read on the GUI thread, without the lock the stage takes: every file it reads
is written whole, so the worst a badly timed read sees is the state a moment
ago, and the window reads again a few seconds later.
"""

from __future__ import annotations

from pathlib import Path

from tasks import nonai_encode
from tasks.nonai_queue import collect_candidates, manifest_entries, relpath
from tasks.nonai_titles import TITLE_FIELD
from tasks.nonai_upscale import StageFiles
from util import nonai_job, processes, sidecar, video_type
from util.upscale_lineup import (
    ASKED_FOR,
    FINISHING,
    PAUSED,
    STARTING,
    UPSCALING,
    Entry,
    Lineup,
    Now,
)


def current(files: StageFiles | None = None) -> Lineup:
    files = StageFiles.configured() if files is None else files
    pinned = set(manifest_entries(files.pin_manifest))
    entries = [_entry(candidate.path, pinned) for candidate in collect_candidates(
        skip_manifest=files.skip_manifest, pin_manifest=files.pin_manifest,
        watch_stats_file=files.watch_stats)]
    now = _now(files, entries, pinned)
    return Lineup(now=now, up_next=tuple(
        entry for entry in entries if now is None or entry.video != now.entry.video))


def _now(files: StageFiles, entries: list[Entry], pinned: set[str]) -> Now | None:
    job = nonai_job.load_job(files.job)
    request = nonai_job.load_request(files.request)
    if job is not None and job.get("source"):
        source = Path(job["source"])
        entry = _known(entries, relpath(source)) or _entry(source, pinned)
        if job.get("pid") and processes.is_running(job["pid"]):
            return Now(entry, _state(job), nonai_encode.percent_encoded(job))
        if request is None:
            return Now(entry, FINISHING)
    if request is not None:
        entry = _known(entries, request.video) or Entry(
            request.video, Path(request.video).stem, None, request.video in pinned)
        return Now(entry, STARTING, held_back=request.held_back)
    return None


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
