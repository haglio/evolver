from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_encode, nonai_progress, nonai_request
from tasks.nonai_encode import EncodeSettings, StartAttempt
from tasks.nonai_files import StageFiles, stage_lock
from tasks.nonai_queue import add_to_skip_list, relpath
from util import (
    ffprobe,
    nonai_job,
    processes,
    provenance,
    sidecar,
)
from util.media_files import reachable, remove_partial_files
from util.nonai_library import buckets, stage_dirs
from util.nonai_retire import carry_funscript, carry_metadata, retire_original
from util.stage_result import StageResult

log = logging.getLogger(__name__)

_USER_IS_BACK = "the user is back at the computer"
_COMPUTER_IS_IDLE = "the computer is idle again"


@dataclass
class NonAiUpscaleResult(StageResult):
    started: str = ""
    in_flight: str = ""
    in_flight_percent: int | None = None
    suspended: bool = False
    promoted: str = ""
    stopped: str = ""
    start_deferred: str = ""
    failed: str = ""
    pending: int = 0
    percent_complete: int | None = None
    remaining_seconds: float = 0.0
    unmeasured_videos: int = 0
    deferred_low_disk: bool = False
    on_request: bool = False
    unreachable_archive: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def needs_an_eye(self) -> bool:
        return self.deferred_low_disk or bool(self.unreachable_archive)


@dataclass(frozen=True)
class Supervision:
    in_flight: str = ""
    in_flight_percent: int | None = None
    suspended: bool = False
    stopped: str = ""
    promoted: str = ""
    failed: str = ""
    deferred_low_disk: bool = False
    unreachable_archive: str = ""


@dataclass(frozen=True)
class Conclusion:
    promoted: str = ""
    failed: str = ""
    unreachable_archive: str = ""


@dataclass(frozen=True)
class RunMode:
    allow_start: bool = True
    stop: bool = False
    presence_managed: bool = False
    take_requests: bool = False
    ai_waiting: bool = False


def run(mode: RunMode | None = None, files: StageFiles | None = None,
        settings: EncodeSettings | None = None) -> NonAiUpscaleResult:
    mode = RunMode() if mode is None else mode
    files = StageFiles.configured() if files is None else files
    settings = EncodeSettings() if settings is None else settings
    result = NonAiUpscaleResult()
    log.info("=== Stage: upscale non-AI library ===")

    with stage_lock:
        job = nonai_job.load_job(files.job)
        if job is None:
            job = nonai_encode.adopt_orphan(files.job)
        _sweep_orphaned_partials(keep=Path(job["tmp"]) if job and "tmp" in job else None)
        request = nonai_job.load_request(files.request) if mode.take_requests else None
        if job is not None and request is not None:
            job, result.stopped = nonai_request.make_way_for(request.video, job, files)
        if job is not None:
            supervised = _supervise(job, files, settings, stop=mode.stop,
                                    presence_managed=mode.presence_managed)
            result.in_flight = supervised.in_flight
            result.in_flight_percent = supervised.in_flight_percent
            result.suspended = supervised.suspended
            result.stopped = result.stopped or supervised.stopped
            result.promoted = supervised.promoted
            result.failed = supervised.failed
            result.deferred_low_disk = supervised.deferred_low_disk
            result.unreachable_archive = supervised.unreachable_archive
            result.on_request = bool(result.in_flight and job.get("on_request"))

        attempt = None
        if not result.in_flight and request is not None:
            attempt = nonai_request.start_requested(
                request, files, settings, ai_waiting=mode.ai_waiting)
            result.on_request = bool(attempt.started)
        elif not result.in_flight and mode.allow_start and not mode.stop:
            attempt = _start_next_queued_video(files, settings)
        if attempt is not None:
            result.started = attempt.started
            result.start_deferred = attempt.deferred
            result.deferred_low_disk |= attempt.deferred_low_disk

    queued = files.queued_videos()
    result.pending = len(queued)
    progress = nonai_progress.so_far(queued_video.path for queued_video in queued)
    result.percent_complete = progress.percent
    result.remaining_seconds = progress.remaining_seconds
    result.unmeasured_videos = progress.unmeasured
    in_flight = result.in_flight or "-"
    if result.in_flight and result.in_flight_percent is not None:
        in_flight = f"{result.in_flight} ({result.in_flight_percent}% encoded)"
    if result.in_flight and result.suspended:
        in_flight = f"{in_flight} [suspended: user present]"
    log.info(
        "Non-AI upscale: started=%s in_flight=%s promoted=%s stopped=%s deferred=%s "
        "failed=%s pending=%d left=%.1fh done=%s unmeasured=%d",
        result.started or "-", in_flight, result.promoted or "-",
        result.stopped or "-", result.start_deferred or "-",
        result.failed or "-", result.pending, result.remaining_seconds / 3600,
        "-" if result.percent_complete is None else f"{result.percent_complete}%",
        result.unmeasured_videos,
    )
    return result


def throttle_to_presence(*, job_file: Path | None = None,
                         settings: EncodeSettings | None = None) -> str:
    job_file = StageFiles.configured(job=job_file).job
    settings = EncodeSettings() if settings is None else settings
    if not stage_lock.acquire(blocking=False):
        return ""
    try:
        return _match_presence(job_file, settings)
    finally:
        stage_lock.release()


def _match_presence(job_file: Path, settings: EncodeSettings) -> str:
    job = nonai_job.load_job(job_file)
    if job is None:
        return ""
    pid = job.get("pid", 0)
    if not pid or not processes.is_running(pid) or job.get("on_request"):
        return ""
    present = nonai_encode.user_present(settings)
    if present and not job.get("suspended"):
        nonai_encode.suspend_job(job, job_file, because=_USER_IS_BACK)
        return "suspended"
    if not present and job.get("suspended"):
        nonai_encode.resume_job(job, job_file, because=_COMPUTER_IS_IDLE)
        return "resumed"
    return ""


def foreign_topaz_running(*, job_file: Path | None = None) -> bool:
    job = nonai_job.load_job(StageFiles.configured(job=job_file).job) or {}
    return any(pid != job.get("pid") for pid in nonai_encode.topaz_pids())


@contextmanager
def frozen_for_ai_videos(*, job_file: Path | None = None) -> Iterator[None]:
    job_file = StageFiles.configured(job=job_file).job
    with stage_lock:
        job = nonai_job.load_job(job_file)
        was_running = (job is not None and not job.get("suspended")
                       and processes.is_running(job.get("pid", 0)))
        if was_running:
            nonai_encode.suspend_job(job, job_file, because="AI videos are upscaling first")
        try:
            yield
        finally:
            if was_running:
                nonai_encode.resume_job(job, job_file, because="the AI videos are done")


def _supervise(job: dict, files: StageFiles, settings: EncodeSettings, *,
               stop: bool = False, presence_managed: bool = False) -> Supervision:
    pid = job.get("pid", 0)
    source = Path(job.get("source", ""))
    if pid and processes.is_running(pid):
        on_request = bool(job.get("on_request"))
        if stop and not on_request:
            return Supervision(
                stopped=nonai_encode.stop_in_flight(job, "the non-AI upscale toggle is off", files))
        if nonai_encode.is_low_disk(settings):
            return Supervision(
                deferred_low_disk=True,
                stopped=nonai_encode.stop_in_flight(
                    job, "free disk fell below the safety floor mid-encode", files),
            )
        if presence_managed and not on_request and nonai_encode.user_present(settings):
            nonai_encode.suspend_job(job, files.job, because=_USER_IS_BACK)
            return Supervision(in_flight=relpath(source), suspended=True,
                               in_flight_percent=nonai_encode.percent_encoded(job))
        if presence_managed or on_request:
            nonai_encode.resume_job(job, files.job,
                                    because=nonai_encode.ASKED_FOR if on_request else _COMPUTER_IS_IDLE)
        if not nonai_encode.overran(job, settings):
            return Supervision(in_flight=relpath(source),
                               in_flight_percent=nonai_encode.percent_encoded(job))
        nonai_encode.terminate_ffmpeg(
            pid, f"it exceeded the {settings.max_runtime_hours}h runtime cap")
    conclusion = _conclude(job, files, settings)
    if conclusion.unreachable_archive:
        return Supervision(in_flight=relpath(source),
                           unreachable_archive=conclusion.unreachable_archive)
    nonai_job.clear_job(files.job)
    return Supervision(promoted=conclusion.promoted, failed=conclusion.failed)


def _conclude(job: dict, files: StageFiles, settings: EncodeSettings) -> Conclusion:
    source = Path(job.get("source", ""))
    tmp = Path(job.get("tmp", ""))
    out = Path(job.get("out", ""))
    expected = job.get("expected_duration") or 0.0
    actual = ffprobe.duration_seconds(tmp) if tmp.is_file() else None
    finished = actual and expected and actual >= settings.complete_duration_fraction * expected
    archive = config.NONAI_RETIRED_ROOT
    if finished and archive is not None and not reachable(archive):
        log.warning("The upscale of %s is finished and waits until %s can be reached to take "
                    "the original.", source, archive)
        return Conclusion(unreachable_archive=str(archive))

    nonai_job.stamp_encode_ended(files.cooldown)
    if finished:
        tmp.replace(out)
        carry_metadata(source, out)
        carry_funscript(source, out)
        stamp = job.get("provenance") or nonai_encode.unrecorded_start()
        sidecar.update(sidecar.sidecar_path(out), lambda current: provenance.recorded(
            current, provenance.UPSCALE_NON_AI, stamp))
        retire_original(source, archive_root=archive)
        nonai_job.clear_attempts(files.attempts, relpath(source))
        log.info("Promoted finished non-AI upscale: %s", out)
        return Conclusion(promoted=relpath(source))

    log.error("Non-AI upscale did not complete (%s): output covers %s of expected %.1fs.",
              source, f"{actual:.1f}s" if actual else "none", expected)
    nonai_encode.delete_tmp(tmp)
    if nonai_job.attempts_of(files.attempts, relpath(source)) >= settings.max_attempts:
        add_to_skip_list(files.skip_list, source,
                             f"failed {settings.max_attempts} attempts")
        nonai_job.clear_attempts(files.attempts, relpath(source))
    return Conclusion(failed=relpath(source))


def _sweep_orphaned_partials(keep: Path | None) -> None:
    for bucket in buckets():
        for _, done_dir in stage_dirs(bucket, digits=(3,)):
            removed = remove_partial_files(done_dir, log, keep=keep)
            if removed:
                log.info("Removed %d stale partial output file(s) from %s", removed, done_dir)


def _start_next_queued_video(files: StageFiles, settings: EncodeSettings) -> StartAttempt:
    if nonai_encode.is_low_disk(settings):
        log.warning("Deferring non-AI upscale start: free disk is below the safety floor.")
        return StartAttempt(deferred_low_disk=True)
    busy = nonai_encode.computer_busy_reason(files.cooldown, settings)
    if busy:
        log.info("Deferring non-AI upscale start: %s.", busy)
        return StartAttempt(deferred=busy)

    for queued_video in files.queued_videos():
        if nonai_encode.start(queued_video, files):
            return StartAttempt(started=relpath(queued_video.path))
    return StartAttempt()
