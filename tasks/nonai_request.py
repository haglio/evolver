from __future__ import annotations

import logging

from tasks import nonai_encode, nonai_queue
from tasks.nonai_encode import EncodeSettings, StartAttempt
from tasks.nonai_files import StageFiles, run_poll_and_window_lock
from tasks.nonai_queue import relpath
from util import nonai_job

log = logging.getLogger(__name__)


def request_now(video: str) -> None:
    files = StageFiles.configured()
    with run_poll_and_window_lock:
        own = _put_ahead(video, files, "you asked for another video now")
        if own is not None:
            _take_over(own, files)
            nonai_job.clear_request(files.request)
            return
        nonai_job.save_request(files.request, nonai_job.Request(video))
        log.info("Asked for the non-AI upscale of %s.", video)


def put_first(video: str) -> None:
    files = StageFiles.configured()
    with run_poll_and_window_lock:
        _put_ahead(video, files, "you put another video first")
        log.info("Put %s first in the non-AI upscale queue.", video)


def withdraw_request() -> None:
    files = StageFiles.configured()
    with run_poll_and_window_lock:
        nonai_job.clear_request(files.request)
        job = nonai_job.load_job(files.job)
        if job is not None and job.withdraw_the_ask():
            nonai_job.save_job(files.job, job)
            log.info("The encode of %s is no longer asked for; it pauses again "
                     "while you are at the computer.", job.source)


def make_way_for(video: str, job: nonai_job.Job,
                 files: StageFiles) -> tuple[nonai_job.Job | None, str]:
    if not job.is_running():
        return job, ""
    if relpath(job.source) == video:
        _take_over(job, files)
        nonai_job.clear_request(files.request)
        return job, ""
    return None, nonai_encode.stop_in_flight(job, "you asked for another video now", files)


def start_requested(request: nonai_job.Request, files: StageFiles,
                    settings: EncodeSettings, *, ai_waiting: bool) -> StartAttempt:
    low_disk = nonai_encode.is_low_disk(settings)
    busy = nonai_encode.LOW_DISK if low_disk else nonai_encode.computer_busy_reason(
        files.cooldown, settings, asked_for=True, ai_waiting=ai_waiting)
    if busy:
        log.info("Holding back the non-AI upscale asked for: %s.", busy)
        nonai_job.save_request(files.request, nonai_job.Request(request.video, held_back=busy))
        return StartAttempt(deferred="" if low_disk else busy, deferred_low_disk=low_disk)
    queued_video = next((queued_video for queued_video in files.queued_videos()
                      if relpath(queued_video.path) == request.video), None)
    nonai_job.clear_request(files.request)
    if queued_video is None or not nonai_encode.start(queued_video, files, on_request=True):
        return StartAttempt()
    return StartAttempt(started=request.video)


def _take_over(job: nonai_job.Job, files: StageFiles) -> None:
    nonai_encode.resume_job(job, files.job, because=nonai_encode.ASKED_FOR)
    job.ask_for()
    nonai_job.save_job(files.job, job)
    log.info("The encode of %s runs on: it is the one asked for.", job.source)


def _put_ahead(video: str, files: StageFiles, why: str) -> nonai_job.Job | None:
    job = nonai_job.load_job(files.job)
    running = job is not None and job.is_running()
    next_after = []
    if running and relpath(job.source) != video:
        next_after.append(nonai_encode.stop_in_flight(job, why, files))
        running = False
    waiting = nonai_job.load_request(files.request)
    if waiting is not None and waiting.video != video:
        next_after.append(waiting.video)
        nonai_job.clear_request(files.request)
    nonai_queue.pin_ahead(files.pin_list, [video, *next_after])
    return job if running else None
