"""Stage: gradually upscale the 2D/non_AI library with its own established recipe.

The non_AI buckets (``larkin``, ``other``, …) hold full-length real-footage
scenes the user has been enhancing by hand in the Topaz GUI: apo-8 60 fps
interpolation plus an iris-2 auto upscale, outputs named ``<stem>_apo8_iris2``
under the bucket's ``3*/processed/`` folder, originals retired to its ``2*``
folder.  This stage automates exactly that convention.

One encode takes hours while the tray watchdog kills a pipeline run at eleven
minutes, so nothing here ever waits on ffmpeg: at most one detached encode is
in flight, and each scheduler tick either checks on it (promote / fail / kill
a stuck one) or starts the next candidate when the machine is otherwise idle.

Once the tray toggle is on, the stage auto-manages that encode by user
presence: it starts or resumes only while the user is away and suspends the
detached ffmpeg the moment they return (frozen, zero compute, resumed exactly
where it left off). A fast GUI poll — ``throttle_to_presence`` — parks and
thaws it between ticks so returning to the machine takes effect in seconds.

A video asked for from the queue window is the one exception: it is wanted
now, so it starts on the next run while the user is at the computer, the toggle
off or the cooldown not yet over, and nothing parks it until it ends or the ask
is withdrawn. Asking stops whatever other encode is in flight; that video keeps
its place in line.

Which clip is next, and why it beat the others, is
:mod:`tasks.nonai_queue`'s, and how far through the whole project the library
is, is :mod:`tasks.nonai_progress`'s; what is left here is the stage: repair,
supervise, maybe start, report.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_encode, nonai_progress, nonai_queue
from tasks.nonai_encode import EncodeSettings
from tasks.nonai_queue import (
    Candidate,
    add_to_skip_list,
    collect_candidates,
    relpath,
)
from util import (
    ffprobe,
    nonai_job,
    orientation,
    processes,
    provenance,
    sidecar,
    system_resources,
    topaz,
)
from util.media_files import partial_path, remove_partial_files
from util.nonai_library import buckets, stage_dirs
from util.nonai_retire import carry_metadata, retire_original

log = logging.getLogger(__name__)

# The full pipeline tick (worker thread) and the fast presence poll (GUI
# thread) both touch the one job file and its ffmpeg. This serializes them so a
# suspend/resume never races a supervise.
_throttle_lock = threading.Lock()

LOW_DISK = "low_disk"

_USER_IS_BACK = "the user is back at the machine"
_MACHINE_IS_IDLE = "the machine is idle again"
_ASKED_FOR = "it is the video asked for now"


@dataclass
class NonAiUpscaleResult:
    started: str = ""
    in_flight: str = ""
    in_flight_percent: int | None = None
    suspended: bool = False  # the in-flight encode is frozen because the user is present
    promoted: str = ""
    stopped: str = ""
    # "user_present" | "topaz_busy" | "low_ram" | "ai_clips_waiting" | "cooldown"
    # | "topaz_sign_in_expired" when a start was held back
    start_deferred: str = ""
    failed: str = ""  # the clip whose encode died or came up short, if any
    pending: int = 0
    # How far along the project is, weighed by running time rather than by clip
    # count -- the two say different things, and by half (tasks.nonai_progress).
    # None until something in the library has a running time recorded.
    percent_complete: int | None = None
    remaining_seconds: float = 0.0
    # Project videos nothing has measured yet, and so in neither total; falls to
    # zero once the video-kinds stage has been over the library.
    unmeasured_videos: int = 0
    deferred_low_disk: bool = False
    # Whether the encode in flight, or the one just started, was asked for from
    # the queue window rather than picked by the stage.
    on_request: bool = False


@dataclass(frozen=True)
class Supervision:
    """What checking on the in-flight encode came to, this tick.

    Either the encode is still going -- named, with how far through it is, and
    frozen or not -- or it has ended, in one of three ways: stopped through no
    fault of its video, promoted over the original, or failed.
    """

    in_flight: str = ""
    in_flight_percent: int | None = None
    suspended: bool = False
    stopped: str = ""
    promoted: str = ""
    failed: str = ""
    deferred_low_disk: bool = False


@dataclass(frozen=True)
class StartAttempt:
    """What trying to start the next encode came to, this tick.

    Either a clip was started, or it was held back -- ``deferred`` naming which
    of the machine's six reasons, and ``deferred_low_disk`` the one that is
    about the library's drive rather than the machine's load.
    """

    started: str = ""
    deferred: str = ""
    deferred_low_disk: bool = False


@dataclass(frozen=True)
class Conclusion:
    """The verdict on an encode that is no longer running.

    Exactly one of the two is set: the output covered enough of the source and
    was promoted over the original, or it did not and the clip failed.
    """

    promoted: str = ""
    failed: str = ""


@dataclass(frozen=True)
class StageFiles:
    """The seven files the stage touches, resolved once at its boundary.

    Four it writes -- the job record, the attempt counter, the cooldown stamp,
    the request from the queue window -- and three the queue reads: the skip
    and pin lists, and Fun Time's watch stats. Held as one record rather
    than threaded separately because every function below is handed the same
    set, and seven separate resolutions put seven conditionals in front of the
    code that supervises a live multi-hour encode -- the one function here that
    most needs to read straight through.
    """

    job: Path
    attempts: Path
    cooldown: Path
    skip_list: Path
    pin_list: Path
    watch_stats: Path
    request: Path

    @classmethod
    def configured(cls, *, job: Path | None = None, attempts: Path | None = None,
                   cooldown: Path | None = None, skip_list: Path | None = None,
                   pin_list: Path | None = None, watch_stats: Path | None = None,
                   request: Path | None = None) -> StageFiles:
        """Each path given, or the configured one where none was.

        Read from ``config`` here rather than as signature defaults: a default
        is evaluated at import, which would put the value out of reach of
        ``override_config``, the seam every stage test steers with.
        """
        return cls(
            job=job or config.NONAI_JOB_STATE_FILE,
            attempts=attempts or config.NONAI_ATTEMPTS_FILE,
            cooldown=cooldown or config.NONAI_COOLDOWN_FILE,
            skip_list=skip_list or config.NONAI_SKIP_LIST,
            pin_list=pin_list or config.NONAI_PIN_LIST,
            watch_stats=watch_stats or config.FUN_TIME_WATCH_STATS_FILE,
            request=request or config.NONAI_REQUEST_FILE,
        )


def run(allow_start: bool = True, stop: bool = False,
        presence_managed: bool = False, *, take_requests: bool = False,
        ai_waiting: bool = False, job_file: Path | None = None,
        attempts_file: Path | None = None, cooldown_file: Path | None = None,
        skip_list: Path | None = None, pin_list: Path | None = None,
        watch_stats_file: Path | None = None, request_file: Path | None = None,
        settings: EncodeSettings | None = None) -> NonAiUpscaleResult:
    """Check on the in-flight encode, then start the next one if the machine is free.

    With *stop* (the tray toggle is off), a still-running encode is killed and
    its video keeps its place in the queue; an already-finished one is still
    promoted, and nothing new starts.

    With *presence_managed* (the toggle is on), the in-flight encode tracks the
    user: it is suspended the moment they touch the machine and resumed once
    they idle out again, so a day of intermittent use makes progress in the
    gaps instead of throwing partial work away. The headless CLI leaves it off
    and simply lets an in-flight encode run.

    Every file the stage touches is named at this boundary and resolved once;
    see :class:`StageFiles`. So is what one encode may cost the machine, which
    is :class:`tasks.nonai_encode.EncodeSettings` -- six numbers this stage
    used to reach for off ``config`` one at a time.
    """
    files = StageFiles.configured(
        job=job_file, attempts=attempts_file, cooldown=cooldown_file,
        skip_list=skip_list, pin_list=pin_list,
        watch_stats=watch_stats_file, request=request_file)
    settings = EncodeSettings() if settings is None else settings
    result = NonAiUpscaleResult()
    log.info("=== Stage: upscale non-AI library ===")

    with _throttle_lock:
        job = nonai_job.load_job(files.job)
        if job is None:
            job = nonai_encode.adopt_orphan(files.job)
        _sweep_orphaned_partials(keep=Path(job["tmp"]) if job and "tmp" in job else None)
        request = nonai_job.load_request(files.request) if take_requests else None
        if job is not None and request is not None:
            job, result.stopped = _make_way_for(request.video, job, files)
        if job is not None:
            supervised = _supervise(job, files, settings, stop=stop,
                                    presence_managed=presence_managed)
            result.in_flight = supervised.in_flight
            result.in_flight_percent = supervised.in_flight_percent
            result.suspended = supervised.suspended
            result.stopped = result.stopped or supervised.stopped
            result.promoted = supervised.promoted
            result.failed = supervised.failed
            result.deferred_low_disk = supervised.deferred_low_disk
            result.on_request = bool(result.in_flight and job.get("on_request"))

        attempt = None
        if not result.in_flight and request is not None:
            attempt = _start_requested(request, files, settings, ai_waiting=ai_waiting)
            result.on_request = bool(attempt.started)
        elif not result.in_flight and allow_start and not stop:
            attempt = _start_next_candidate(files, settings)
        if attempt is not None:
            result.started = attempt.started
            result.start_deferred = attempt.deferred
            result.deferred_low_disk |= attempt.deferred_low_disk

    # Collected a second time on purpose: a start attempt can retire clips to
    # the skip list, and the count reported is the queue as it stands after
    # that. The doubled walk is finding tasks/design/008's; merging the two
    # would change what `pending` means, so it stays and stays visible.
    queued = _collect(files)
    result.pending = len(queued)
    # Handed the queue just collected: nonai_progress reads sidecars and walks
    # the buckets for what is upscaled, and need not redo this walk too.
    progress = nonai_progress.so_far(candidate.path for candidate in queued)
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
    """Between full pipeline ticks, keep the in-flight encode in step with the
    user: suspend it the moment they return, resume it once they idle out.

    Cheap enough for a short GUI timer — it touches only the one live job, with
    no candidate scan or disk work. Returns "suspended", "resumed", or "" when
    nothing changed. Starting a new encode stays with the pipeline tick, which
    has the candidate scan and resource checks; this only parks and thaws.
    """
    job_file = StageFiles.configured(job=job_file).job
    settings = EncodeSettings() if settings is None else settings
    if not _throttle_lock.acquire(blocking=False):
        return ""
    try:
        return _match_presence(job_file, settings)
    finally:
        _throttle_lock.release()


def _match_presence(job_file: Path, settings: EncodeSettings) -> str:
    job = nonai_job.load_job(job_file)
    if job is None:
        return ""
    pid = job.get("pid", 0)
    if not pid or not processes.is_running(pid) or job.get("on_request"):
        return ""
    present = _user_present(settings)
    if present and not job.get("suspended"):
        nonai_encode.suspend_job(job, job_file, because=_USER_IS_BACK)
        return "suspended"
    if not present and job.get("suspended"):
        nonai_encode.resume_job(job, job_file, because=_MACHINE_IS_IDLE)
        return "resumed"
    return ""


def foreign_topaz_running(*, job_file: Path | None = None) -> bool:
    job = nonai_job.load_job(StageFiles.configured(job=job_file).job) or {}
    return any(pid != job.get("pid") for pid in nonai_encode.topaz_pids())


@contextmanager
def frozen_for_ai_clips(*, job_file: Path | None = None) -> Iterator[None]:
    job_file = StageFiles.configured(job=job_file).job
    with _throttle_lock:
        job = nonai_job.load_job(job_file)
        was_running = (job is not None and not job.get("suspended")
                       and processes.is_running(job.get("pid", 0)))
        if was_running:
            nonai_encode.suspend_job(job, job_file, because="AI clips are upscaling first")
        try:
            yield
        finally:
            if was_running:
                nonai_encode.resume_job(job, job_file, because="the AI clips are done")


def _collect(files: StageFiles) -> list[Candidate]:
    return collect_candidates(skip_list=files.skip_list,
                              pin_list=files.pin_list,
                              watch_stats_file=files.watch_stats)


def _supervise(job: dict, files: StageFiles, settings: EncodeSettings, *,
               stop: bool = False, presence_managed: bool = False) -> Supervision:
    pid = job.get("pid", 0)
    source = Path(job.get("source", ""))
    if pid and processes.is_running(pid):
        on_request = bool(job.get("on_request"))
        if stop and not on_request:
            return Supervision(
                stopped=_stop_in_flight(job, "the non-AI upscale toggle is off", files))
        if _is_low_disk():
            # The floor was clear at start, but a 4K60 output plus whatever
            # else writes overnight can cross it mid-encode.
            return Supervision(
                deferred_low_disk=True,
                stopped=_stop_in_flight(
                    job, "free disk fell below the safety floor mid-encode", files),
            )
        if presence_managed and not on_request and _user_present(settings):
            nonai_encode.suspend_job(job, files.job, because=_USER_IS_BACK)
            return Supervision(in_flight=relpath(source), suspended=True,
                               in_flight_percent=nonai_encode.percent_encoded(job))
        if presence_managed or on_request:
            nonai_encode.resume_job(job, files.job,
                                    because=_ASKED_FOR if on_request else _MACHINE_IS_IDLE)
        if not nonai_encode.overran(job, settings):
            return Supervision(in_flight=relpath(source),
                               in_flight_percent=nonai_encode.percent_encoded(job))
        nonai_encode.terminate_ffmpeg(
            pid, f"it exceeded the {settings.max_runtime_hours}h runtime cap")
    conclusion = _conclude(job, files, settings)
    nonai_job.clear_job(files.job)
    return Supervision(promoted=conclusion.promoted, failed=conclusion.failed)


def _stop_in_flight(job: dict, reason: str, files: StageFiles) -> str:
    """End the encode through no fault of its video — no retry penalty.

    Answers the clip that was stopped, which keeps its place in the queue.
    """
    source = Path(job.get("source", ""))
    nonai_encode.terminate_ffmpeg(job.get("pid", 0), reason)
    nonai_encode.delete_tmp(Path(job.get("tmp", "")))
    nonai_job.clear_attempts(files.attempts, relpath(source))
    nonai_job.clear_job(files.job)
    log.info("Stopped the in-flight non-AI upscale of %s; it stays queued.", source)
    return relpath(source)


def _make_way_for(video: str, job: dict, files: StageFiles) -> tuple[dict | None, str]:
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
    return None, _stop_in_flight(job, "you asked for another video now", files)


def _take_over(job: dict, files: StageFiles) -> None:
    """Let the encode already running stand as the one that was asked for."""
    nonai_encode.resume_job(job, files.job, because=_ASKED_FOR)
    job["on_request"] = True
    nonai_job.save_job(files.job, job)
    log.info("The encode of %s runs on: it is the one asked for.", job.get("source"))


def request_now(video: str) -> None:
    """Ask for *video* to be upscaled right away, and clear the way for it.

    The queue window's door, called the moment the arrow on a video is
    switched on. It records the ask and gets the machine out of its way; the
    encode itself starts on the next pipeline run, which is the one place a
    Topaz process is ever launched.

    An encode of another video is stopped here rather than on that run, so the
    AI clips the run upscales first are not held back by a Topaz process this
    request is about to end anyway.
    """
    files = StageFiles.configured()
    with _throttle_lock:
        own = _put_ahead(video, files, "you asked for another video now")
        if own is not None:
            _take_over(own, files)
            nonai_job.clear_request(files.request)
            return
        nonai_job.save_request(files.request, nonai_job.Request(video))
        log.info("Asked for the non-AI upscale of %s.", video)


def put_first(video: str) -> None:
    """Make *video* the next one upscaled, at the usual moment for starting one.

    The queue window's door for a video dragged to the top of the list.
    """
    files = StageFiles.configured()
    with _throttle_lock:
        _put_ahead(video, files, "you put another video first")
        log.info("Put %s first in the non-AI upscale queue.", video)


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
        next_after.append(_stop_in_flight(job, why, files))
        running = False
    waiting = nonai_job.load_request(files.request)
    if waiting is not None and waiting.video != video:
        next_after.append(waiting.video)
        nonai_job.clear_request(files.request)
    nonai_queue.pin_ahead(files.pin_list, [video, *next_after])
    return job if running else None


def withdraw_request() -> None:
    """Stop asking for the video :func:`request_now` asked for.

    It keeps its place at the head of the queue and goes back to the usual
    rule: upscaled while nobody is at the computer.
    """
    files = StageFiles.configured()
    with _throttle_lock:
        nonai_job.clear_request(files.request)
        job = nonai_job.load_job(files.job)
        if job is not None and job.pop("on_request", None):
            nonai_job.save_job(files.job, job)
            log.info("The encode of %s is no longer asked for; it pauses again "
                     "while you are at the computer.", job.get("source"))


def _conclude(job: dict, files: StageFiles, settings: EncodeSettings) -> Conclusion:
    source = Path(job.get("source", ""))
    tmp = Path(job.get("tmp", ""))
    out = Path(job.get("out", ""))
    expected = job.get("expected_duration") or 0.0
    actual = ffprobe.duration_seconds(tmp) if tmp.is_file() else None

    nonai_job.stamp_encode_ended(files.cooldown)
    if actual and expected and actual >= settings.complete_duration_fraction * expected:
        tmp.replace(out)
        # Before the original leaves, and it takes its sidecar with it.
        carry_metadata(source, out)
        stamp = job.get("provenance") or nonai_encode.unrecorded_start()
        sidecar.update(sidecar.sidecar_path(out), lambda current: provenance.recorded(
            current, provenance.UPSCALE_NON_AI, stamp))
        retire_original(source, archive_root=config.NONAI_RETIRED_ROOT)
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
    """Delete leftover ``.partial.`` outputs no live job owns.

    A crash between launching ffmpeg and a later conclusion can strand one;
    the live job's own tmp is exempt. A partial a lingering ffmpeg still has
    open just fails to unlink and gets swept on a later tick.
    """
    for bucket in buckets():
        for _, done_dir in stage_dirs(bucket, digits=(3,)):
            removed = remove_partial_files(done_dir, log, keep=keep)
            if removed:
                log.info("Removed %d stale partial output file(s) from %s", removed, done_dir)


def _start_next_candidate(files: StageFiles, settings: EncodeSettings) -> StartAttempt:
    if _is_low_disk():
        log.warning("Deferring non-AI upscale start: free disk is below the safety floor.")
        return StartAttempt(deferred_low_disk=True)
    busy = _machine_busy_reason(files.cooldown, settings)
    if busy:
        log.info("Deferring non-AI upscale start: %s.", busy)
        return StartAttempt(deferred=busy)

    for candidate in _collect(files):
        if _launch(candidate, files):
            return StartAttempt(started=relpath(candidate.path))
    return StartAttempt()


def _start_requested(request: nonai_job.Request, files: StageFiles,
                     settings: EncodeSettings, *, ai_waiting: bool) -> StartAttempt:
    low_disk = _is_low_disk()
    busy = LOW_DISK if low_disk else _machine_busy_reason(
        files.cooldown, settings, asked_for=True, ai_waiting=ai_waiting)
    if busy:
        log.info("Holding back the non-AI upscale asked for: %s.", busy)
        nonai_job.save_request(files.request, nonai_job.Request(request.video, held_back=busy))
        return StartAttempt(deferred="" if low_disk else busy, deferred_low_disk=low_disk)
    candidate = next((candidate for candidate in _collect(files)
                      if relpath(candidate.path) == request.video), None)
    nonai_job.clear_request(files.request)
    if candidate is None or not _launch(candidate, files, on_request=True):
        return StartAttempt()
    return StartAttempt(started=request.video)


def _launch(candidate: Candidate, files: StageFiles, *, on_request: bool = False) -> bool:
    """Start *candidate*'s encode, or retire it to the skip list unstarted."""
    source = candidate.path
    expected_duration = ffprobe.duration_seconds(source)
    orient = ffprobe.orientation_of(source)
    if ffprobe.videoai_tag(source):
        add_to_skip_list(files.skip_list, source,
                             "already carries a Topaz videoai tag")
        return False
    if expected_duration is None or orient == orientation.UNKNOWN:
        add_to_skip_list(files.skip_list, source,
                             "ffprobe could not read duration or orientation")
        return False

    out = _output_path(candidate)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(out, source.stem)
    nonai_job.bump_attempts(files.attempts, relpath(source))
    pid = nonai_encode.launch(source, tmp, orient)
    job = {
        "pid": pid,
        "source": str(source),
        "tmp": str(tmp),
        "out": str(out),
        "expected_duration": expected_duration,
        "started_at": time.time(),
        "provenance": provenance.by_evolver(recipe=topaz.NON_AI_UPSCALE.name,
                                            recipe_version=topaz.NON_AI_UPSCALE.version),
    }
    if on_request:
        job["on_request"] = True
    nonai_job.save_job(files.job, job)
    log.info("Started detached non-AI upscale (pid %d%s): %s -> %s",
             pid, ", asked for" if on_request else "", source, out)
    return True


def _output_path(candidate: Candidate) -> Path:
    done_dirs = stage_dirs(candidate.bucket, digits=(3,))
    done_dir = (
        done_dirs[0][1] if done_dirs
        else candidate.bucket / config.NONAI_FALLBACK_DONE_DIR_NAME
    )
    stem = candidate.path.stem
    return done_dir / config.NONAI_PROCESSED_DIR_NAME / f"{stem}{config.NONAI_OUTPUT_SUFFIX}.mp4"


def _is_low_disk() -> bool:
    free_gb = system_resources.free_bytes(config.NON_AI_DIR) / (1024 ** 3)
    return free_gb < config.LOW_DISK_WARNING_GB


def _machine_busy_reason(cooldown_file: Path, settings: EncodeSettings, *,
                         asked_for: bool = False, ai_waiting: bool = False) -> str:
    """Why the machine cannot take a new encode right now — "" when it can.

    A present user comes first: an unattended multi-hour encode has no business
    starting while someone is at the keyboard. Any live Topaz ffmpeg — an
    orphaned encode or the user's own GUI export — already owns the GPU, and CPU
    sampling never sees that. RAM and a post-encode cooldown keep an unattended
    night from running the machine flat out end to end.

    A video *asked_for* from the queue window is wanted now, so the user being
    at the computer and the cooldown do not hold it back; the rest still do, and
    so do new AI clips still *ai_waiting*, since none of them can run beside it.
    """
    if not asked_for and _user_present(settings):
        return "user_present"
    if nonai_encode.topaz_pids():
        return "topaz_busy"
    if system_resources.available_ram_gb() < settings.min_available_ram_gb:
        return "low_ram"
    if ai_waiting:
        return "ai_clips_waiting"
    if not asked_for and (time.time() - nonai_job.last_encode_ended_at(cooldown_file)
                          < settings.cooldown_minutes * 60):
        return "cooldown"
    if topaz.sign_in_expired():
        return topaz.SIGN_IN_EXPIRED
    return ""


def _user_present(settings: EncodeSettings) -> bool:
    """Whether the user has touched the machine recently.

    On any failure to read the idle time, err toward present: holding back an
    unattended encode is always safer than hogging a machine someone is using.
    """
    try:
        idle = system_resources.seconds_since_last_input()
    except OSError:
        return True
    return idle < settings.user_idle_threshold_seconds
