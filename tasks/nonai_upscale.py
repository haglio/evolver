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

Which clip is next, and why it beat the others, is
:mod:`tasks.nonai_queue`'s, and how far through the whole project the library
is, is :mod:`tasks.nonai_progress`'s; what is left here is the stage: repair,
supervise, maybe start, report.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_encode, nonai_progress
from tasks.nonai_queue import (
    Candidate,
    add_to_skip_manifest,
    collect_candidates,
    relpath,
)
from util import ffprobe, nonai_job, processes, sidecar, system_resources
from util.media_files import is_finalized_video_file, is_partial_video_path
from util.nonai_library import buckets, stage_dirs
from util.nonai_retire import archived_original, carry_metadata, retire_original
from util.variants import is_processed_stem, strip_processing_suffixes
from util import orientation

log = logging.getLogger(__name__)

# The full pipeline tick (worker thread) and the fast presence poll (GUI
# thread) both touch the one job file and its ffmpeg. This serializes them so a
# suspend/resume never races a supervise.
_throttle_lock = threading.Lock()


@dataclass
class NonAiUpscaleResult:
    started: str = ""
    in_flight: str = ""
    in_flight_percent: int | None = None
    suspended: bool = False  # the in-flight encode is frozen because the user is present
    promoted: str = ""
    stopped: str = ""
    # "user_present" | "topaz_busy" | "low_ram" | "cooldown" when a start was held back
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
    # Upscales promoted before their sidecar was carried across, handed it back
    # off the retired original — see :func:`repair_retired_metadata`.
    repaired_sidecars: int = 0


@dataclass(frozen=True)
class StageFiles:
    """The six files the stage touches, resolved once at its boundary.

    Three it writes -- the job record, the attempt counter, the cooldown stamp
    -- and three the queue reads: the skip and pin manifests, and Fun Time's
    watch stats. Held as one record rather than threaded separately because
    every function below is handed the same set, and six separate resolutions
    put six conditionals in front of the code that supervises a live multi-hour
    encode -- the one function here that most needs to read straight through.
    """

    job: Path
    attempts: Path
    cooldown: Path
    skip_manifest: Path
    pin_manifest: Path
    watch_stats: Path


def _configured_files(job_file: Path | None, attempts_file: Path | None,
                      cooldown_file: Path | None, skip_manifest: Path | None,
                      pin_manifest: Path | None,
                      watch_stats_file: Path | None) -> StageFiles:
    """Each argument, or the configured path when the caller named none.

    The sentinel form -- ``x=None``, then ``config.X if x is None else x`` --
    rather than signature defaults: a default is evaluated at import, which
    would freeze whatever ``config`` held then and put the value out of reach
    of ``override_config``, the seam every stage test steers with.
    """
    return StageFiles(
        job=config.NONAI_JOB_STATE_FILE if job_file is None else job_file,
        attempts=config.NONAI_ATTEMPTS_FILE if attempts_file is None else attempts_file,
        cooldown=config.NONAI_COOLDOWN_FILE if cooldown_file is None else cooldown_file,
        skip_manifest=(config.NONAI_SKIP_MANIFEST if skip_manifest is None
                       else skip_manifest),
        pin_manifest=(config.NONAI_PRIORITY_MANIFEST if pin_manifest is None
                      else pin_manifest),
        watch_stats=(config.FUN_TIME_WATCH_STATS_FILE if watch_stats_file is None
                     else watch_stats_file),
    )


def run(allow_start: bool = True, stop: bool = False,
        presence_managed: bool = False, *, job_file: Path | None = None,
        attempts_file: Path | None = None, cooldown_file: Path | None = None,
        skip_manifest: Path | None = None, pin_manifest: Path | None = None,
        watch_stats_file: Path | None = None) -> NonAiUpscaleResult:
    """Check on the in-flight encode, then start the next one if the box is free.

    With *stop* (the tray toggle is off), a still-running encode is killed and
    its video keeps its place in the queue; an already-finished one is still
    promoted, and nothing new starts.

    With *presence_managed* (the toggle is on), the in-flight encode tracks the
    user: it is suspended the moment they touch the machine and resumed once
    they idle out again, so a day of intermittent use makes progress in the
    gaps instead of throwing partial work away. The headless CLI leaves it off
    and simply lets an in-flight encode run.

    Every file the stage touches is named at this boundary and resolved once;
    see :class:`StageFiles`.
    """
    files = _configured_files(job_file, attempts_file, cooldown_file,
                              skip_manifest, pin_manifest, watch_stats_file)
    result = NonAiUpscaleResult()
    log.info("=== Stage: upscale non-AI library ===")

    repair_retired_metadata(result)

    with _throttle_lock:
        job = nonai_job.load_job(files.job)
        if job is None:
            job = nonai_encode.adopt_orphan(files.job)
        _sweep_orphaned_partials(keep=Path(job["tmp"]) if job and "tmp" in job else None)
        if job is not None:
            _supervise(job, result, files, stop=stop,
                       presence_managed=presence_managed)

        if not result.in_flight and allow_start and not stop:
            _start_next_candidate(result, files)

    # Collected a second time on purpose: a start attempt can retire clips to
    # the skip manifest, and the count reported is the queue as it stands after
    # that. The doubled walk is finding tasks/design/008's; merging the two
    # would change what `pending` means, so it stays and stays visible.
    queued = _collect(files)
    result.pending = len(queued)
    _report_progress(result, queued)
    in_flight = result.in_flight or "-"
    if result.in_flight and result.in_flight_percent is not None:
        in_flight = f"{result.in_flight} ({result.in_flight_percent}% encoded)"
    if result.in_flight and result.suspended:
        in_flight = f"{in_flight} [suspended: user present]"
    log.info(
        "Non-AI upscale: started=%s in_flight=%s promoted=%s stopped=%s deferred=%s "
        "failed=%s pending=%d left=%.1fh done=%s unmeasured=%d repaired=%d sidecar(s)",
        result.started or "-", in_flight, result.promoted or "-",
        result.stopped or "-", result.start_deferred or "-",
        result.failed or "-", result.pending, result.remaining_seconds / 3600,
        "-" if result.percent_complete is None else f"{result.percent_complete}%",
        result.unmeasured_videos, result.repaired_sidecars,
    )
    return result


def _report_progress(result: NonAiUpscaleResult, queued: list[Candidate]) -> None:
    """Put how far along the project is on *result*, in running time.

    Handed the queue the stage just collected rather than collecting it again:
    :mod:`tasks.nonai_progress` reads sidecars and walks the buckets for what is
    already upscaled, and there is no reason for it to redo this walk too.
    """
    progress = nonai_progress.so_far(candidate.path for candidate in queued)
    result.percent_complete = progress.percent
    result.remaining_seconds = progress.remaining_seconds
    result.unmeasured_videos = progress.unmeasured


def throttle_to_presence(*, job_file: Path | None = None) -> str:
    """Between full pipeline ticks, keep the in-flight encode in step with the
    user: suspend it the moment they return, resume it once they idle out.

    Cheap enough for a short GUI timer — it touches only the one live job, with
    no candidate scan or disk work. Returns "suspended", "resumed", or "" when
    nothing changed. Starting a new encode stays with the pipeline tick, which
    has the candidate scan and resource checks; this only parks and thaws.
    """
    job_file = config.NONAI_JOB_STATE_FILE if job_file is None else job_file
    with _throttle_lock:
        job = nonai_job.load_job(job_file)
        if job is None:
            return ""
        pid = job.get("pid", 0)
        if not pid or not processes.is_running(pid):
            return ""
        present = _user_present()
        if present and not job.get("suspended"):
            nonai_encode.suspend_job(job, job_file)
            return "suspended"
        if not present and job.get("suspended"):
            nonai_encode.resume_job(job, job_file)
            return "resumed"
        return ""


def _collect(files: StageFiles) -> list[Candidate]:
    return collect_candidates(skip_manifest=files.skip_manifest,
                              pin_manifest=files.pin_manifest,
                              watch_stats_file=files.watch_stats)


def _supervise(job: dict, result: NonAiUpscaleResult, files: StageFiles, *,
               stop: bool = False, presence_managed: bool = False) -> None:
    pid = job.get("pid", 0)
    source = Path(job.get("source", ""))
    if pid and processes.is_running(pid):
        if stop:
            _stop_in_flight(job, result, "the non-AI upscale toggle is off", files)
            return
        if _is_low_disk():
            # The 250 GB floor was clear at start, but a 4K60 output plus
            # whatever else writes overnight can cross it mid-encode.
            result.deferred_low_disk = True
            _stop_in_flight(job, result,
                            "free disk fell below the safety floor mid-encode", files)
            return
        if presence_managed and _user_present():
            nonai_encode.suspend_job(job, files.job)
            result.in_flight = relpath(source)
            result.in_flight_percent = nonai_encode.percent_encoded(job)
            result.suspended = True
            return
        if presence_managed:
            nonai_encode.resume_job(job, files.job)  # a no-op unless it was frozen
        if not nonai_encode.overran(job):
            result.in_flight = relpath(source)
            result.in_flight_percent = nonai_encode.percent_encoded(job)
            return
        nonai_encode.terminate_ffmpeg(pid, f"it exceeded the {config.NONAI_MAX_RUNTIME_HOURS}h runtime cap")
    _conclude(job, result, files)
    nonai_job.clear_job(files.job)


def _stop_in_flight(job: dict, result: NonAiUpscaleResult, reason: str,
                    files: StageFiles) -> None:
    """End the encode through no fault of its video — no retry penalty."""
    source = Path(job.get("source", ""))
    nonai_encode.terminate_ffmpeg(job.get("pid", 0), reason)
    nonai_encode.delete_tmp(Path(job.get("tmp", "")))
    nonai_job.clear_attempts(files.attempts, relpath(source))
    nonai_job.clear_job(files.job)
    result.stopped = relpath(source)
    log.info("Stopped the in-flight non-AI upscale of %s; it stays queued.", source)


def _conclude(job: dict, result: NonAiUpscaleResult, files: StageFiles) -> None:
    source = Path(job.get("source", ""))
    tmp = Path(job.get("tmp", ""))
    out = Path(job.get("out", ""))
    expected = job.get("expected_duration") or 0.0
    actual = ffprobe.duration_seconds(tmp) if tmp.is_file() else None

    nonai_job.stamp_encode_ended(files.cooldown)
    if actual and expected and actual >= config.NONAI_COMPLETE_DURATION_FRACTION * expected:
        tmp.replace(out)
        # Before the original leaves, and it takes its sidecar with it.
        carry_metadata(source, out)
        retire_original(source, archive_root=config.NONAI_RETIRED_ROOT)
        nonai_job.clear_attempts(files.attempts, relpath(source))
        result.promoted = relpath(source)
        log.info("Promoted finished non-AI upscale: %s", out)
        return

    result.failed = relpath(source)
    log.error("Non-AI upscale did not complete (%s): output covers %s of expected %.1fs.",
              source, f"{actual:.1f}s" if actual else "none", expected)
    nonai_encode.delete_tmp(tmp)
    if nonai_job.attempts_of(files.attempts, relpath(source)) >= config.NONAI_MAX_ATTEMPTS:
        add_to_skip_manifest(files.skip_manifest, source,
                             f"failed {config.NONAI_MAX_ATTEMPTS} attempts")
        nonai_job.clear_attempts(files.attempts, relpath(source))


def repair_retired_metadata(result: NonAiUpscaleResult) -> None:
    """Hand back what upscales promoted before :func:`_carry_metadata` existed lost.

    Their originals were archived whole — video and sidecar together — so
    nothing was destroyed, only moved out of reach: this finds each stranded
    upscale's original in the archive and carries the record across now, as
    promotion would have.  Idempotent, so it costs a scan and nothing else once
    the library is whole; it runs ahead of the clip-scripts stage, which needs
    the record restored to cut a clip its own funscript.

    Only an upscale with no ``clip`` record is a candidate.  A cut is the only
    kind of video that carries one, so a whole video that never had a record has
    nothing here to be missing, and one that has its record is already sound.
    """
    if config.NONAI_RETIRED_ROOT is None or not config.NONAI_RETIRED_ROOT.is_dir():
        return
    for bucket in buckets():
        archived = config.NONAI_RETIRED_ROOT / bucket.relative_to(config.NON_AI_DIR)
        if not archived.is_dir():
            continue
        for video in sorted(bucket.rglob("*")):
            if not is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
                continue
            if not is_processed_stem(video.stem):
                continue
            if isinstance(sidecar.read(sidecar.sidecar_path(video)).get("clip"), dict):
                continue
            original = archived_original(archived, strip_processing_suffixes(video.stem))
            if original is None:
                continue
            result.repaired_sidecars += int(carry_metadata(original, video))


def _sweep_orphaned_partials(keep: Path | None) -> None:
    """Delete leftover ``.partial.`` outputs no live job owns.

    A crash between launching ffmpeg and a later conclusion can strand one;
    the live job's own tmp is exempt. A partial a lingering ffmpeg still has
    open just fails to unlink and gets swept on a later tick.
    """
    for bucket in buckets():
        for _, done_dir in stage_dirs(bucket, digits=(3,)):
            removed = 0
            for path in done_dir.rglob("*.partial.*"):
                if keep is not None and path == keep:
                    continue
                if not is_partial_video_path(path) or path.suffix.lower() not in config.VIDEO_EXTENSIONS:
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    log.exception("Failed to delete stale partial output: %s", path)
            if removed:
                log.info("Removed %d stale partial output file(s) from %s", removed, done_dir)


def _start_next_candidate(result: NonAiUpscaleResult, files: StageFiles) -> None:
    if _is_low_disk():
        result.deferred_low_disk = True
        log.warning("Deferring non-AI upscale start: free disk is below the safety floor.")
        return
    result.start_deferred = _machine_busy_reason(files.cooldown)
    if result.start_deferred:
        log.info("Deferring non-AI upscale start: %s.", result.start_deferred)
        return

    for candidate in _collect(files):
        source = candidate.path
        expected_duration = ffprobe.duration_seconds(source)
        orient = ffprobe.get_orientation(source)
        if ffprobe.videoai_tag(source):
            add_to_skip_manifest(files.skip_manifest, source,
                                 "already carries a Topaz videoai tag")
            continue
        if expected_duration is None or orient == orientation.UNKNOWN:
            add_to_skip_manifest(files.skip_manifest, source,
                                 "ffprobe could not read duration or orientation")
            continue

        out = _output_path(candidate)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{source.stem}.partial.{uuid.uuid4().hex}.mp4")
        nonai_job.bump_attempts(files.attempts, relpath(source))
        pid = nonai_encode.launch(source, tmp, orient)
        nonai_job.save_job(files.job, {
            "pid": pid,
            "source": str(source),
            "tmp": str(tmp),
            "out": str(out),
            "expected_duration": expected_duration,
            "started_at": time.time(),
        })
        result.started = relpath(source)
        log.info("Started detached non-AI upscale (pid %d): %s -> %s", pid, source, out)
        return


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


def _machine_busy_reason(cooldown_file: Path) -> str:
    """Why the machine cannot take a new encode right now — "" when it can.

    A present user comes first: an unattended multi-hour encode has no business
    starting while someone is at the keyboard. Any live Topaz ffmpeg — an
    orphaned encode or the user's own GUI export — already owns the GPU, and CPU
    sampling never sees that. RAM and a post-encode cooldown keep an unattended
    night from running the box flat out end to end.
    """
    if _user_present():
        return "user_present"
    if processes.pids_of_image(config.FFMPEG):
        return "topaz_busy"
    if system_resources.available_ram_gb() < config.NONAI_MIN_AVAILABLE_RAM_GB:
        return "low_ram"
    if (time.time() - nonai_job.last_encode_ended_at(cooldown_file)
            < config.NONAI_COOLDOWN_MINUTES * 60):
        return "cooldown"
    return ""


def _user_present() -> bool:
    """Whether the user has touched the machine recently.

    On any failure to read the idle time, err toward present: holding back an
    unattended encode is always safer than hogging a machine someone is using.
    """
    try:
        idle = system_resources.seconds_since_last_input()
    except OSError:
        return True
    return idle < config.NONAI_USER_IDLE_THRESHOLD_SECONDS
