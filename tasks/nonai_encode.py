from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support import processes
from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import seconds_since_input

import config
from tasks.nonai_files import StageFiles
from tasks.nonai_queue import QueuedVideo, add_to_skip_list, relpath
from util import ffprobe, nonai_job, orientation, provenance, system_resources, topaz
from util.media_files import is_partial_path, partial_path, partial_stem
from util.nonai_library import stage_dirs

log = logging.getLogger(__name__)

_LOG_WARNINGS_AND_PROGRESS_ONLY = ("-loglevel", "warning", "-stats")

LOW_DISK = "low_disk"
ASKED_FOR = "it is the video asked for now"


@dataclass(frozen=True)
class EncodeSettings:
    max_runtime_hours: float = 24
    max_attempts: int = 2
    died_partway_if_covering_less_than: float = 0.98
    min_available_ram_gb: float = 8.0
    min_free_disk_gb: float = 250.0
    cooldown_minutes: int = 30
    away_once_idle_past_a_reading_pause_seconds: float = 300.0


@dataclass(frozen=True)
class StartAttempt:
    started: str = ""
    deferred: str = ""
    deferred_low_disk: bool = False


def unrecorded_start() -> dict:
    return provenance.reconstructed("evolver", method=topaz.NON_AI_UPSCALE.name)


def topaz_pids() -> list[int]:
    return [encode.pid for encode in _topaz_encodes()]


def _topaz_encodes() -> list[processes.Process]:
    topaz = str(config.FFMPEG).lower()
    return [process for process in processes.running() if process.exe.lower() == topaz]


def adopt_orphan(job_file: Path) -> nonai_job.Job | None:
    encodes = _topaz_encodes()
    if len(encodes) != 1:
        return None
    pid = encodes[0].pid
    source, tmp = _parse_topaz_arguments(encodes[0].arguments)
    if source is None or tmp is None or not is_partial_path(tmp):
        return None
    try:
        tmp.relative_to(config.NON_AI_DIR)
    except ValueError:
        return None
    adopted_at = time.time()
    job = nonai_job.Job.adopted(
        pid=pid, source=source, tmp=tmp,
        out=tmp.with_name(f"{partial_stem(tmp)}{config.NONAI_OUTPUT_SUFFIX}.mp4"),
        expected_duration=ffprobe.duration_seconds(source) or 0.0,
        started_at=adopted_at, provenance=unrecorded_start())
    processes.resume(pid)
    nonai_job.save_job(job_file, job)
    log.warning(
        "Adopted an orphaned non-AI encode (pid %d) of %s; its job state had gone missing.",
        pid, source,
    )
    return job


def _parse_topaz_arguments(arguments: tuple[str, ...]) -> tuple[Path | None, Path | None]:
    try:
        source = arguments[arguments.index("-i") + 1]
    except (ValueError, IndexError):
        return None, None
    return Path(source), Path(arguments[-1])


def suspend_job(job: nonai_job.Job, job_file: Path, *, because: str) -> None:
    if job.suspended:
        return
    processes.suspend(job.pid)
    job.suspend(now=time.time())
    nonai_job.save_job(job_file, job)
    log.info("Suspended the non-AI encode of %s; %s.", job.source, because)


def resume_job(job: nonai_job.Job, job_file: Path, *, because: str) -> None:
    if not job.suspended:
        return
    processes.resume(job.pid)
    job.resume(now=time.time())
    nonai_job.save_job(job_file, job)
    log.info("Resumed the non-AI encode of %s; %s.", job.source, because)


def overran(job: nonai_job.Job, settings: EncodeSettings, *, now: float | None = None) -> bool:
    runtime = job.active_runtime(now=time.time() if now is None else now)
    return runtime > settings.max_runtime_hours * 3600


def percent_encoded(job: nonai_job.Job) -> int | None:
    tmp = job.tmp
    expected = job.expected_duration
    # ffmpeg writes fragmented mp4 (topaz.command's -movflags), so the partial probes mid-write.
    encoded = ffprobe.duration_seconds(tmp) if tmp.is_file() else None
    if not encoded or not expected:
        return None
    return min(100, round(encoded / expected * 100))


def terminate_ffmpeg(pid: int, reason: str) -> None:
    image = processes.exe_of(pid)
    if image and Path(image).name.lower() == config.FFMPEG.name.lower():
        log.warning("Killing non-AI upscale ffmpeg (pid %d): %s.", pid, reason)
        processes.terminate(pid)
    else:
        log.warning("Job pid %d is no longer ffmpeg; treating the encode as ended.", pid)


def delete_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        # Windows refuses while a just-ended ffmpeg still holds the file; a later sweep takes it.
        log.exception("Could not delete partial output %s yet.", tmp)


def launch(source: Path, tmp: Path, orient: str) -> int:
    ffmpeg, *arguments = topaz.command(source, tmp, topaz.framed(topaz.NON_AI_UPSCALE, orient))
    with open(config.NONAI_FFMPEG_LOG, "w", encoding="utf-8") as ffmpeg_log:
        proc = subprocess.Popen(
            [ffmpeg, *_LOG_WARNINGS_AND_PROGRESS_ONLY, *arguments],
            env=topaz.environment(),
            stdout=subprocess.DEVNULL,
            stderr=ffmpeg_log,
            **hidden_subprocess_kwargs(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS),
        )
    return proc.pid


def start(queued_video: QueuedVideo, files: StageFiles, *, on_request: bool = False) -> bool:
    source = queued_video.path
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

    out = _output_path(queued_video)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(out, source.stem)
    nonai_job.bump_attempts(files.attempts, relpath(source))
    pid = launch(source, tmp, orient)
    job = nonai_job.Job.started(
        pid=pid, source=source, tmp=tmp, out=out, expected_duration=expected_duration,
        started_at=time.time(),
        provenance=provenance.by_evolver(method=topaz.NON_AI_UPSCALE.name,
                                         method_version=topaz.NON_AI_UPSCALE.version),
        on_request=on_request)
    nonai_job.save_job(files.job, job)
    log.info("Started detached non-AI upscale (pid %d%s): %s -> %s",
             pid, ", asked for" if on_request else "", source, out)
    return True


def _output_path(queued_video: QueuedVideo) -> Path:
    done_dirs = stage_dirs(queued_video.bucket, digits=(3,))
    done_dir = (
        done_dirs[0][1] if done_dirs
        else queued_video.bucket / config.NONAI_FALLBACK_DONE_DIR_NAME
    )
    stem = queued_video.path.stem
    return done_dir / config.NONAI_PROCESSED_DIR_NAME / f"{stem}{config.NONAI_OUTPUT_SUFFIX}.mp4"


def stop_in_flight(job: nonai_job.Job, reason: str, files: StageFiles) -> str:
    source = job.source
    terminate_ffmpeg(job.pid, reason)
    delete_tmp(job.tmp)
    nonai_job.clear_attempts(files.attempts, relpath(source))
    nonai_job.clear_job(files.job)
    log.info("Stopped the in-flight non-AI upscale of %s; it stays queued.", source)
    return relpath(source)


def is_low_disk(settings: EncodeSettings) -> bool:
    return system_resources.free_gb(config.NON_AI_DIR) < settings.min_free_disk_gb


def computer_busy_reason(cooldown_file: Path, settings: EncodeSettings, *,
                        asked_for: bool = False, ai_waiting: bool = False) -> str:
    checks = busy_checks(cooldown_file, settings, asked_for=asked_for, ai_waiting=ai_waiting)
    return next((reason for reason, applies in checks if applies()), "")


def busy_checks(cooldown_file: Path, settings: EncodeSettings, *, asked_for: bool,
                ai_waiting: bool) -> tuple[tuple[str, Callable[[], object]], ...]:
    return (
        ("user_present", lambda: not asked_for and user_present(settings)),
        # A live Topaz ffmpeg owns the graphics card, which the CPU reading never sees.
        ("topaz_busy", topaz_pids),
        ("low_ram", lambda: system_resources.available_ram_gb() < settings.min_available_ram_gb),
        ("ai_clips_waiting", lambda: ai_waiting),
        ("cooldown", lambda: not asked_for and _cooling_down(cooldown_file, settings)),
        (topaz.SIGN_IN_EXPIRED, topaz.sign_in_expired),
    )


def _cooling_down(cooldown_file: Path, settings: EncodeSettings) -> bool:
    since_last_encode = time.time() - nonai_job.last_encode_ended_at(cooldown_file)
    return since_last_encode < settings.cooldown_minutes * 60


def user_present(settings: EncodeSettings, *, idle_seconds=None) -> bool:
    try:
        idle = (idle_seconds or seconds_since_input)()
    except OSError:
        return True
    return idle < settings.away_once_idle_past_a_reading_pause_seconds
