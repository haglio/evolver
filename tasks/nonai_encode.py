from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import seconds_since_input

import config
from tasks.nonai_files import StageFiles
from tasks.nonai_queue import QueuedVideo, add_to_skip_list, relpath
from util import ffprobe, nonai_job, orientation, processes, provenance, system_resources, topaz
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
    complete_duration_fraction: float = 0.98
    min_available_ram_gb: float = 8.0
    min_free_disk_gb: float = 250.0
    cooldown_minutes: int = 30
    user_idle_threshold_seconds: float = 300.0


@dataclass(frozen=True)
class StartAttempt:
    started: str = ""
    deferred: str = ""
    deferred_low_disk: bool = False


def unrecorded_start() -> dict:
    return provenance.reconstructed("evolver", method=topaz.NON_AI_UPSCALE.name)


def topaz_pids() -> list[int]:
    return processes.pids_of_image(config.FFMPEG)


def adopt_orphan(job_file: Path) -> dict | None:
    pids = topaz_pids()
    if len(pids) != 1:
        return None
    source, tmp = _parse_topaz_command(processes.command_line(pids[0]) or "")
    if source is None or tmp is None or not is_partial_path(tmp):
        return None
    try:
        tmp.relative_to(config.NON_AI_DIR)
    except ValueError:
        return None
    job = {
        "pid": pids[0],
        "source": str(source),
        "tmp": str(tmp),
        "out": str(tmp.with_name(f"{partial_stem(tmp)}{config.NONAI_OUTPUT_SUFFIX}.mp4")),
        "expected_duration": ffprobe.duration_seconds(source) or 0.0,
        "started_at": time.time(),
        "suspended": False,
        "suspended_at": 0.0,
        "suspended_seconds": 0.0,
        "provenance": unrecorded_start(),
    }
    processes.resume(pids[0])
    nonai_job.save_job(job_file, job)
    log.warning(
        "Adopted an orphaned non-AI encode (pid %d) of %s; its job state had gone missing.",
        pids[0], source,
    )
    return job


def _parse_topaz_command(cmdline: str) -> tuple[Path | None, Path | None]:
    token = r'(?:"([^"]+)"|(\S+))'
    source_match = re.search(rf"-i\s+{token}", cmdline)
    output_match = re.search(rf"{token}\s*$", cmdline)
    if not source_match or not output_match:
        return None, None
    source = source_match.group(1) or source_match.group(2)
    output = output_match.group(1) or output_match.group(2)
    return Path(source), Path(output)


def suspend_job(job: dict, job_file: Path, *, because: str) -> None:
    if job.get("suspended"):
        return
    processes.suspend(job.get("pid", 0))
    job["suspended"] = True
    job["suspended_at"] = time.time()
    nonai_job.save_job(job_file, job)
    log.info("Suspended the non-AI encode of %s; %s.", job.get("source"), because)


def resume_job(job: dict, job_file: Path, *, because: str) -> None:
    if not job.get("suspended"):
        return
    processes.resume(job.get("pid", 0))
    paused_for = time.time() - job.get("suspended_at", time.time())
    job["suspended_seconds"] = job.get("suspended_seconds", 0.0) + paused_for
    job["suspended"] = False
    job["suspended_at"] = 0.0
    nonai_job.save_job(job_file, job)
    log.info("Resumed the non-AI encode of %s; %s.", job.get("source"), because)


def overran(job: dict, settings: EncodeSettings, *, now: float | None = None) -> bool:
    return active_runtime(job, now=now) > settings.max_runtime_hours * 3600


def active_runtime(job: dict, *, now: float | None = None) -> float:
    now = time.time() if now is None else now
    suspended = job.get("suspended_seconds", 0.0)
    if job.get("suspended") and job.get("suspended_at"):
        suspended += now - job["suspended_at"]
    return now - job.get("started_at", now) - suspended


def percent_encoded(job: dict) -> int | None:
    tmp = Path(job.get("tmp", ""))
    expected = job.get("expected_duration") or 0.0
    encoded = ffprobe.duration_seconds(tmp) if tmp.is_file() else None
    if not encoded or not expected:
        return None
    return min(100, round(encoded / expected * 100))


def terminate_ffmpeg(pid: int, reason: str) -> None:
    image = processes.image_path(pid)
    if image and Path(image).name.lower() == config.FFMPEG.name.lower():
        log.warning("Killing non-AI upscale ffmpeg (pid %d): %s.", pid, reason)
        processes.terminate(pid)
    else:
        log.warning("Job pid %d is no longer ffmpeg; treating the encode as ended.", pid)


def delete_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
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
    job = {
        "pid": pid,
        "source": str(source),
        "tmp": str(tmp),
        "out": str(out),
        "expected_duration": expected_duration,
        "started_at": time.time(),
        "provenance": provenance.by_evolver(method=topaz.NON_AI_UPSCALE.name,
                                            method_version=topaz.NON_AI_UPSCALE.version),
    }
    if on_request:
        job["on_request"] = True
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


def stop_in_flight(job: dict, reason: str, files: StageFiles) -> str:
    source = Path(job.get("source", ""))
    terminate_ffmpeg(job.get("pid", 0), reason)
    delete_tmp(Path(job.get("tmp", "")))
    nonai_job.clear_attempts(files.attempts, relpath(source))
    nonai_job.clear_job(files.job)
    log.info("Stopped the in-flight non-AI upscale of %s; it stays queued.", source)
    return relpath(source)


def is_low_disk(settings: EncodeSettings) -> bool:
    return system_resources.free_gb(config.NON_AI_DIR) < settings.min_free_disk_gb


def computer_busy_reason(cooldown_file: Path, settings: EncodeSettings, *,
                        asked_for: bool = False, ai_waiting: bool = False) -> str:
    if not asked_for and user_present(settings):
        return "user_present"
    if topaz_pids():
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


def user_present(settings: EncodeSettings, *, idle_seconds=seconds_since_input) -> bool:
    try:
        idle = idle_seconds()
    except OSError:
        return True
    return idle < settings.user_idle_threshold_seconds
