"""The video asked for now, from the Upscale Queue window.

An encode the stage picks for itself starts only while nobody is at the
computer and is parked the moment somebody is. The video asked for is the one
exception: it starts on the next run whoever is at the computer, the toggle off
or the cooldown not yet over, and nothing parks it until it ends or the ask is
withdrawn. Asking stops whatever other encode is in flight, which keeps its
place in line.

The three verbs here are the window's doors, taken under the stage's lock the
moment they are asked; what a run does with the ask -- make way for it, start
it -- is here too, called from the stage's tick.
"""

from __future__ import annotations

import logging
from pathlib import Path

from tasks import nonai_encode, nonai_queue
from tasks.nonai_encode import EncodeSettings, StartAttempt
from tasks.nonai_files import StageFiles, stage_lock
from tasks.nonai_queue import relpath
from util import nonai_job, processes

log = logging.getLogger(__name__)


def request_now(video: str) -> None:
    """Ask for *video* to be upscaled right away, and clear the way for it.

    An encode of another video is stopped here rather than on the next run, so
    the AI clips that run upscales first are not held back by a Topaz process
    this request is about to end anyway. The encode itself starts on that run,
    the one place a Topaz process is ever launched.
    """
    files = StageFiles.configured()
    with stage_lock:
        own = _put_ahead(video, files, "you asked for another video now")
        if own is not None:
            _take_over(own, files)
            nonai_job.clear_request(files.request)
            return
        nonai_job.save_request(files.request, nonai_job.Request(video))
        log.info("Asked for the non-AI upscale of %s.", video)


def put_first(video: str) -> None:
    """Make *video* the next one upscaled, at the usual moment for starting one."""
    files = StageFiles.configured()
    with stage_lock:
        _put_ahead(video, files, "you put another video first")
        log.info("Put %s first in the non-AI upscale queue.", video)


def withdraw_request() -> None:
    """Stop asking: the video keeps its place at the head of the queue and goes
    back to the usual rule, upscaled while nobody is at the computer."""
    files = StageFiles.configured()
    with stage_lock:
        nonai_job.clear_request(files.request)
        job = nonai_job.load_job(files.job)
        if job is not None and job.pop("on_request", None):
            nonai_job.save_job(files.job, job)
            log.info("The encode of %s is no longer asked for; it pauses again "
                     "while you are at the computer.", job.get("source"))


def make_way_for(video: str, job: dict, files: StageFiles) -> tuple[dict | None, str]:
    """The job left in flight once *video* has the machine, and what was stopped.

    An encode that has already ended is left alone for supervision to conclude:
    it may be a finished upscale.
    """
    if not (job.get("pid") and processes.is_running(job["pid"])):
        return job, ""
    if relpath(Path(job["source"])) == video:
        _take_over(job, files)
        nonai_job.clear_request(files.request)
        return job, ""
    return None, nonai_encode.stop_in_flight(job, "you asked for another video now", files)


def start_requested(request: nonai_job.Request, files: StageFiles,
                    settings: EncodeSettings, *, ai_waiting: bool) -> StartAttempt:
    """Start the video asked for, or record what is holding it back."""
    low_disk = nonai_encode.is_low_disk(settings)
    busy = nonai_encode.LOW_DISK if low_disk else nonai_encode.machine_busy_reason(
        files.cooldown, settings, asked_for=True, ai_waiting=ai_waiting)
    if busy:
        log.info("Holding back the non-AI upscale asked for: %s.", busy)
        nonai_job.save_request(files.request, nonai_job.Request(request.video, held_back=busy))
        return StartAttempt(deferred="" if low_disk else busy, deferred_low_disk=low_disk)
    candidate = next((candidate for candidate in files.candidates()
                      if relpath(candidate.path) == request.video), None)
    nonai_job.clear_request(files.request)
    if candidate is None or not nonai_encode.start(candidate, files, on_request=True):
        return StartAttempt()
    return StartAttempt(started=request.video)


def _take_over(job: dict, files: StageFiles) -> None:
    """Let the encode already running stand as the one that was asked for."""
    nonai_encode.resume_job(job, files.job, because=nonai_encode.ASKED_FOR)
    job["on_request"] = True
    nonai_job.save_job(files.job, job)
    log.info("The encode of %s runs on: it is the one asked for.", job.get("source"))


def _put_ahead(video: str, files: StageFiles, why: str) -> dict | None:
    """Pin *video* first, and move whatever stood there to just after it.

    Another video's encode is stopped, and another video's ask is dropped:
    only the first video is upscaled, and only the first can be asked for.
    Answers *video*'s own encode when that is the one in flight.
    """
    job = nonai_job.load_job(files.job)
    running = bool(job and job.get("pid") and processes.is_running(job["pid"]))
    next_after = []
    if running and relpath(Path(job["source"])) != video:
        next_after.append(nonai_encode.stop_in_flight(job, why, files))
        running = False
    waiting = nonai_job.load_request(files.request)
    if waiting is not None and waiting.video != video:
        next_after.append(waiting.video)
        nonai_job.clear_request(files.request)
    nonai_queue.pin_ahead(files.pin_list, [video, *next_after])
    return job if running else None
