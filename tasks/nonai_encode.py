"""The detached encode itself: start it, adopt it, freeze it, measure it, kill it.

One non-AI encode takes hours while the tray watchdog kills a pipeline run at
eleven minutes, so nothing here ever waits on ffmpeg. What it does instead is
everything that touches the process: launching it detached with the non-AI
recipe, rebuilding the record for one whose job file went missing, suspending
and resuming it as the user comes and goes, reading how far it has got off the
partial it is still writing, and killing it.

Whether any of that should happen is :mod:`tasks.nonai_upscale`'s -- the
tick's decision. What that decision is weighed against is :class:`EncodeSettings`,
which lives here rather than in ``config``: how long an encode may run and how
much of the machine it may take are this app's own policy, not anything the
machine or the overlay says, and ``config`` is for the second kind.

The encode recipe -- the target edges, the filter template, the videoai tag --
and the encoder's own log stay ambient config here, the way VIDEO_EXTENSIONS
does: one repo-wide answer to "what does a non-AI upscale look like", not
something a caller varies. The job record's file is a parameter, because the
stage owns where its state lives.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from util import ffprobe, nonai_job, orientation, processes, topaz

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EncodeSettings:
    """What one unattended non-AI encode may cost the machine, and when.

    Six numbers the stage used to reach for off ``config`` one at a time, so
    its signature said nothing about what governed it and a test moving one
    patched a module attribute rather than passing a value. They are one record
    because they are one policy: how long an encode may run, how complete its
    output has to be to be believed, how many tries a clip gets, and the two
    conditions the machine has to meet before the next one starts.
    """

    max_runtime_hours: float = 24
    max_attempts: int = 2
    # How much of the source's running time the output has to cover to be
    # believed. Short of it, the encode is treated as having died partway.
    complete_duration_fraction: float = 0.98
    min_available_ram_gb: float = 8.0
    cooldown_minutes: int = 30
    # Presence throttle: once the toggle is on, Evolver auto-manages the encode
    # by how long the user has been away from the keyboard/mouse. Below this
    # idle threshold the user counts as present -- no new encode starts and any
    # in-flight one is suspended (frozen, zero compute); past it the machine is
    # "away" and an encode may start or resume. Five minutes rides out ordinary
    # reading/watching pauses without treating them as the user leaving.
    user_idle_threshold_seconds: float = 300.0


def adopt_orphan(job_file: Path) -> dict | None:
    """Rebuild the job record for a lone still-running encode of ours.

    The job file can vanish out from under a live encode: the sync service
    covering the project tree renames it mid-run. Without the record the encode
    is orphaned — unsupervised, never promoted, and no longer blocking new
    starts. A single Topaz ffmpeg whose output is one of our .partial files in
    the non-AI tree is unambiguously ours, so it is adopted back under
    supervision.
    """
    pids = processes.pids_of_image(config.FFMPEG)
    if len(pids) != 1:
        return None
    source, tmp = _parse_topaz_command(processes.command_line(pids[0]) or "")
    if source is None or tmp is None or ".partial." not in tmp.name:
        return None
    try:
        tmp.relative_to(config.NON_AI_DIR)
    except ValueError:
        return None  # some other Topaz run, e.g. a manual GUI export
    stem = tmp.name.split(".partial.")[0]
    job = {
        "pid": pids[0],
        "source": str(source),
        "tmp": str(tmp),
        "out": str(tmp.with_name(f"{stem}{config.NONAI_OUTPUT_SUFFIX}.mp4")),
        "expected_duration": ffprobe.duration_seconds(source) or 0.0,
        # The true start time is unknown; counting the runtime cap from
        # adoption is the conservative reading.
        "started_at": time.time(),
        "suspended": False,
        "suspended_at": 0.0,
        "suspended_seconds": 0.0,
    }
    # A crash could have left the encode frozen; thaw it so adoption never
    # inherits a permanently-suspended process. resume() no-ops if it is
    # already running.
    processes.resume(pids[0])
    nonai_job.save_job(job_file, job)
    log.warning(
        "Adopted an orphaned non-AI encode (pid %d) of %s; its job state had gone missing.",
        pids[0], source,
    )
    return job


def _parse_topaz_command(cmdline: str) -> tuple[Path | None, Path | None]:
    """The -i input and the trailing output of a Topaz ffmpeg command line."""
    token = r'(?:"([^"]+)"|(\S+))'
    source_match = re.search(rf"-i\s+{token}", cmdline)
    output_match = re.search(rf"{token}\s*$", cmdline)
    if not source_match or not output_match:
        return None, None
    source = source_match.group(1) or source_match.group(2)
    output = output_match.group(1) or output_match.group(2)
    return Path(source), Path(output)


def suspend_job(job: dict, job_file: Path) -> None:
    """Freeze the encode and remember when, so the pause is not charged runtime."""
    if job.get("suspended"):
        return
    processes.suspend(job.get("pid", 0))
    job["suspended"] = True
    job["suspended_at"] = time.time()
    nonai_job.save_job(job_file, job)
    log.info("Suspended the non-AI encode of %s; the user is back at the machine.",
             job.get("source"))


def resume_job(job: dict, job_file: Path) -> None:
    """Thaw the encode and bank the time it spent frozen."""
    if not job.get("suspended"):
        return
    processes.resume(job.get("pid", 0))
    paused_for = time.time() - job.get("suspended_at", time.time())
    job["suspended_seconds"] = job.get("suspended_seconds", 0.0) + paused_for
    job["suspended"] = False
    job["suspended_at"] = 0.0
    nonai_job.save_job(job_file, job)
    log.info("Resumed the non-AI encode of %s; the machine is idle again.",
             job.get("source"))


def overran(job: dict, settings: EncodeSettings, *, now: float | None = None) -> bool:
    return active_runtime(job, now=now) > settings.max_runtime_hours * 3600


def active_runtime(job: dict, *, now: float | None = None) -> float:
    """Wall-clock since the encode started, minus the time it spent suspended.

    The runtime cap exists to catch a *stuck* encode; hours parked frozen while
    the user was at the machine are not the encode's fault and must not count.

    *now* is the moment to measure against, defaulting to this one. It is an
    argument because this arithmetic is what decides that a live multi-hour
    encode is stuck and kills it, and against the wall clock the only way to
    ask it a question is to build a job that started a chosen number of seconds
    ago and accept the answer to within the test's own runtime.
    """
    now = time.time() if now is None else now
    suspended = job.get("suspended_seconds", 0.0)
    if job.get("suspended") and job.get("suspended_at"):
        suspended += now - job["suspended_at"]
    return now - job.get("started_at", now) - suspended


def percent_encoded(job: dict) -> int | None:
    """How far the running encode has gotten, read off its growing partial.

    ffmpeg writes fragmented mp4, so the partial is probeable mid-write; its
    duration over the source's is the encode's progress.
    """
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
        # The pid was recycled by an unrelated process; our ffmpeg is already gone.
        log.warning("Job pid %d is no longer ffmpeg; treating the encode as ended.", pid)


def delete_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        # A just-killed ffmpeg can briefly hold the file; the partial sweep
        # removes it on a later tick.
        log.exception("Could not delete partial output %s yet.", tmp)


def launch(source: Path, tmp: Path, orient: str) -> int:
    width, height = (
        (config.NONAI_TARGET_LONG_EDGE, config.NONAI_TARGET_SHORT_EDGE)
        if orient == orientation.LANDSCAPE
        else (config.NONAI_TARGET_SHORT_EDGE, config.NONAI_TARGET_LONG_EDGE)
    )
    filter_complex = config.NONAI_UPSCALE_FILTER_TEMPLATE.format(width=width, height=height)
    cmd = topaz.command(source, tmp, filter_complex, config.VIDEOAI_TAG_NONAI, keep_audio=True)
    with open(config.NONAI_FFMPEG_LOG, "w", encoding="utf-8") as ffmpeg_log:
        proc = subprocess.Popen(
            cmd,
            env=topaz.environment(),
            stdout=subprocess.DEVNULL,
            stderr=ffmpeg_log,
            **hidden_subprocess_kwargs(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS),
        )
    return proc.pid
