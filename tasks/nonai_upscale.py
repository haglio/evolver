"""Stage: gradually upscale the 2D/non_AI library with its own established recipe.

The non_AI buckets (``winston``, ``other``, …) hold full-length real-footage
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

Candidates come from the buckets' triage folders (``0 unsorted``, ``1 could
use work``), most-wanted first: an explicit ``1`` flag beats everything, then
clips with a funscript — the only per-video engagement signal the non_AI
library has, since Fun Time's watch stats cover only the AI outbox.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import config
from util import ffprobe, processes, system_resources, topaz
from util.media_files import is_finalized_video_file, is_partial_video_path
from util.nonai_library import buckets
from util.variants import is_processed_stem, strip_processing_suffixes

log = logging.getLogger(__name__)

# The full pipeline tick (worker thread) and the fast presence poll (GUI
# thread) both touch the one job file and its ffmpeg. This serializes them so a
# suspend/resume never races a supervise.
_throttle_lock = threading.Lock()


@dataclass(frozen=True)
class Candidate:
    path: Path
    bucket: Path
    triage_digit: int
    has_funscript: bool
    watch_score: float


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
    deferred_low_disk: bool = False


def run(allow_start: bool = True, stop: bool = False,
        presence_managed: bool = False) -> NonAiUpscaleResult:
    """Check on the in-flight encode, then start the next one if the box is free.

    With *stop* (the tray toggle is off), a still-running encode is killed and
    its video keeps its place in the queue; an already-finished one is still
    promoted, and nothing new starts.

    With *presence_managed* (the toggle is on), the in-flight encode tracks the
    user: it is suspended the moment they touch the machine and resumed once
    they idle out again, so a day of intermittent use makes progress in the
    gaps instead of throwing partial work away. The headless CLI leaves it off
    and simply lets an in-flight encode run.
    """
    result = NonAiUpscaleResult()
    log.info("=== Stage: upscale non-AI library ===")

    with _throttle_lock:
        job = _load_job()
        if job is None:
            job = _adopt_orphan()
        _sweep_orphaned_partials(keep=Path(job["tmp"]) if job and "tmp" in job else None)
        if job is not None:
            _supervise(job, result, stop=stop, presence_managed=presence_managed)

        if not result.in_flight and allow_start and not stop:
            _start_next_candidate(result)

    result.pending = len(collect_candidates())
    in_flight = result.in_flight or "-"
    if result.in_flight and result.in_flight_percent is not None:
        in_flight = f"{result.in_flight} ({result.in_flight_percent}% encoded)"
    if result.in_flight and result.suspended:
        in_flight = f"{in_flight} [suspended: user present]"
    log.info(
        "Non-AI upscale: started=%s in_flight=%s promoted=%s stopped=%s deferred=%s failed=%s pending=%d",
        result.started or "-", in_flight, result.promoted or "-",
        result.stopped or "-", result.start_deferred or "-",
        result.failed or "-", result.pending,
    )
    return result


def throttle_to_presence() -> str:
    """Between full pipeline ticks, keep the in-flight encode in step with the
    user: suspend it the moment they return, resume it once they idle out.

    Cheap enough for a short GUI timer — it touches only the one live job, with
    no candidate scan or disk work. Returns "suspended", "resumed", or "" when
    nothing changed. Starting a new encode stays with the pipeline tick, which
    has the candidate scan and resource checks; this only parks and thaws.
    """
    with _throttle_lock:
        job = _load_job()
        if job is None:
            return ""
        pid = job.get("pid", 0)
        if not pid or not processes.is_running(pid):
            return ""
        present = _user_present()
        if present and not job.get("suspended"):
            _suspend_job(job)
            return "suspended"
        if not present and job.get("suspended"):
            _resume_job(job)
            return "resumed"
        return ""


def _adopt_orphan() -> dict | None:
    """Rebuild the job record for a lone still-running encode of ours.

    The job file can vanish out from under a live encode (the sync service
    covering the project tree renamed it mid-run more than once). Losing it
    used to orphan the encode — unsupervised, never promoted, and no longer
    blocking new starts, so encodes stacked up. A single Topaz ffmpeg whose
    output is one of our .partial files in the non-AI tree is unambiguously
    ours, so it is adopted back under supervision.
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
    _save_job(job)
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


def _supervise(job: dict, result: NonAiUpscaleResult, stop: bool = False,
               presence_managed: bool = False) -> None:
    pid = job.get("pid", 0)
    source = Path(job.get("source", ""))
    if pid and processes.is_running(pid):
        if stop:
            _stop_in_flight(job, result, "the non-AI upscale toggle is off")
            return
        if _is_low_disk():
            # The 250 GB floor was clear at start, but a 4K60 output plus
            # whatever else writes overnight can cross it mid-encode.
            result.deferred_low_disk = True
            _stop_in_flight(job, result, "free disk fell below the safety floor mid-encode")
            return
        if presence_managed and _user_present():
            _suspend_job(job)
            result.in_flight = relpath(source)
            result.in_flight_percent = _percent_encoded(job)
            result.suspended = True
            return
        if presence_managed:
            _resume_job(job)  # a no-op unless it was frozen
        if not _overran(job):
            result.in_flight = relpath(source)
            result.in_flight_percent = _percent_encoded(job)
            return
        _terminate_ffmpeg(pid, f"it exceeded the {config.NONAI_MAX_RUNTIME_HOURS}h runtime cap")
    _conclude(job, result)
    _clear_job()


def _suspend_job(job: dict) -> None:
    """Freeze the encode and remember when, so the pause is not charged runtime."""
    if job.get("suspended"):
        return
    processes.suspend(job.get("pid", 0))
    job["suspended"] = True
    job["suspended_at"] = time.time()
    _save_job(job)
    log.info("Suspended the non-AI encode of %s; the user is back at the machine.",
             job.get("source"))


def _resume_job(job: dict) -> None:
    """Thaw the encode and bank the time it spent frozen."""
    if not job.get("suspended"):
        return
    processes.resume(job.get("pid", 0))
    paused_for = time.time() - job.get("suspended_at", time.time())
    job["suspended_seconds"] = job.get("suspended_seconds", 0.0) + paused_for
    job["suspended"] = False
    job["suspended_at"] = 0.0
    _save_job(job)
    log.info("Resumed the non-AI encode of %s; the machine is idle again.",
             job.get("source"))


def _stop_in_flight(job: dict, result: NonAiUpscaleResult, reason: str) -> None:
    """End the encode through no fault of its video — no retry penalty."""
    source = Path(job.get("source", ""))
    _terminate_ffmpeg(job.get("pid", 0), reason)
    _delete_tmp(Path(job.get("tmp", "")))
    _clear_attempts(source)
    _clear_job()
    result.stopped = relpath(source)
    log.info("Stopped the in-flight non-AI upscale of %s; it stays queued.", source)


def _overran(job: dict) -> bool:
    return _active_runtime(job) > config.NONAI_MAX_RUNTIME_HOURS * 3600


def _active_runtime(job: dict) -> float:
    """Wall-clock since the encode started, minus the time it spent suspended.

    The runtime cap exists to catch a *stuck* encode; hours parked frozen while
    the user was at the machine are not the encode's fault and must not count.
    """
    now = time.time()
    suspended = job.get("suspended_seconds", 0.0)
    if job.get("suspended") and job.get("suspended_at"):
        suspended += now - job["suspended_at"]
    return now - job.get("started_at", now) - suspended


def _percent_encoded(job: dict) -> int | None:
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


def _terminate_ffmpeg(pid: int, reason: str) -> None:
    image = processes.image_path(pid)
    if image and Path(image).name.lower() == config.FFMPEG.name.lower():
        log.warning("Killing non-AI upscale ffmpeg (pid %d): %s.", pid, reason)
        processes.terminate(pid)
    else:
        # The pid was recycled by an unrelated process; our ffmpeg is already gone.
        log.warning("Job pid %d is no longer ffmpeg; treating the encode as ended.", pid)


def _conclude(job: dict, result: NonAiUpscaleResult) -> None:
    source = Path(job.get("source", ""))
    tmp = Path(job.get("tmp", ""))
    out = Path(job.get("out", ""))
    expected = job.get("expected_duration") or 0.0
    actual = ffprobe.duration_seconds(tmp) if tmp.is_file() else None

    _stamp_encode_ended()
    if actual and expected and actual >= config.NONAI_COMPLETE_DURATION_FRACTION * expected:
        tmp.replace(out)
        _retire_original(source)
        _clear_attempts(source)
        result.promoted = relpath(source)
        log.info("Promoted finished non-AI upscale: %s", out)
        return

    result.failed = relpath(source)
    log.error("Non-AI upscale did not complete (%s): output covers %s of expected %.1fs.",
              source, f"{actual:.1f}s" if actual else "none", expected)
    _delete_tmp(tmp)
    if _attempts_of(source) >= config.NONAI_MAX_ATTEMPTS:
        _add_to_skip_manifest(source, f"failed {config.NONAI_MAX_ATTEMPTS} attempts")
        _clear_attempts(source)


def _delete_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        # A just-killed ffmpeg can briefly hold the file; the partial sweep
        # removes it on a later tick.
        log.exception("Could not delete partial output %s yet.", tmp)


def _retire_original(source: Path) -> None:
    """Move the processed original into its bucket's ``2*`` folder, as the user does."""
    bucket = _bucket_of(source)
    retire_dirs = _numbered_dirs(bucket, digits=(2,)) if bucket else []
    if not retire_dirs:
        log.warning("No '2*' folder in %s; leaving the original at %s.", bucket, source)
        return
    dest = retire_dirs[0][1] / source.name
    if dest.exists():
        log.warning("Original collides with %s; leaving it at %s.", dest, source)
        return
    source.replace(dest)
    log.info("Retired original: %s -> %s", source, dest)


def _bucket_of(source: Path) -> Path | None:
    try:
        return config.NON_AI_DIR / source.relative_to(config.NON_AI_DIR).parts[0]
    except ValueError:
        return None


def _sweep_orphaned_partials(keep: Path | None) -> None:
    """Delete leftover ``.partial.`` outputs no live job owns.

    A crash between launching ffmpeg and a later conclusion can strand one;
    the live job's own tmp is exempt. A partial a lingering ffmpeg still has
    open just fails to unlink and gets swept on a later tick.
    """
    for bucket in buckets():
        for _, done_dir in _numbered_dirs(bucket, digits=(3,)):
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


def _start_next_candidate(result: NonAiUpscaleResult) -> None:
    if _is_low_disk():
        result.deferred_low_disk = True
        log.warning("Deferring non-AI upscale start: free disk is below the safety floor.")
        return
    result.start_deferred = _machine_busy_reason()
    if result.start_deferred:
        log.info("Deferring non-AI upscale start: %s.", result.start_deferred)
        return

    for candidate in collect_candidates():
        source = candidate.path
        expected_duration = ffprobe.duration_seconds(source)
        orientation = ffprobe.get_orientation(source)
        if ffprobe.videoai_tag(source):
            _add_to_skip_manifest(source, "already carries a Topaz videoai tag")
            continue
        if expected_duration is None or orientation == "unknown":
            _add_to_skip_manifest(source, "ffprobe could not read duration or orientation")
            continue

        out = _output_path(candidate)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{source.stem}.partial.{uuid.uuid4().hex}.mp4")
        _bump_attempts(source)
        pid = _launch(source, tmp, orientation)
        _save_job({
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


def _launch(source: Path, tmp: Path, orientation: str) -> int:
    width, height = (
        (config.NONAI_TARGET_LONG_EDGE, config.NONAI_TARGET_SHORT_EDGE)
        if orientation == "landscape"
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
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )
    return proc.pid


def _output_path(candidate: Candidate) -> Path:
    done_dirs = _numbered_dirs(candidate.bucket, digits=(3,))
    done_dir = (
        done_dirs[0][1] if done_dirs
        else candidate.bucket / config.NONAI_FALLBACK_DONE_DIR_NAME
    )
    stem = candidate.path.stem
    return done_dir / config.NONAI_PROCESSED_DIR_NAME / f"{stem}{config.NONAI_OUTPUT_SUFFIX}.mp4"


def _is_low_disk() -> bool:
    free_gb = system_resources.free_bytes(config.NON_AI_DIR) / (1024 ** 3)
    return free_gb < config.LOW_DISK_WARNING_GB


def _machine_busy_reason() -> str:
    """Why the machine cannot take a new encode right now — "" when it can.

    A present user comes first: an unattended multi-hour encode has no business
    starting while someone is at the keyboard. Any live Topaz ffmpeg — an
    orphaned encode or the user's own GUI export — already owns the GPU; CPU
    sampling never sees that, which is how encodes stacked up and crashed the
    machine. RAM and a post-encode cooldown keep an unattended night from
    running the box flat out end to end.
    """
    if _user_present():
        return "user_present"
    if processes.pids_of_image(config.FFMPEG):
        return "topaz_busy"
    if system_resources.available_ram_gb() < config.NONAI_MIN_AVAILABLE_RAM_GB:
        return "low_ram"
    if time.time() - _last_encode_ended_at() < config.NONAI_COOLDOWN_MINUTES * 60:
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


def _last_encode_ended_at() -> float:
    try:
        payload = json.loads(config.NONAI_COOLDOWN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    ended_at = payload.get("ended_at", 0.0) if isinstance(payload, dict) else 0.0
    return ended_at if isinstance(ended_at, (int, float)) else 0.0


def _stamp_encode_ended() -> None:
    config.NONAI_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.NONAI_COOLDOWN_FILE.write_text(
        json.dumps({"ended_at": time.time()}), encoding="utf-8"
    )


def _load_job() -> dict | None:
    try:
        payload = json.loads(config.NONAI_JOB_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_job(job: dict) -> None:
    config.NONAI_JOB_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.NONAI_JOB_STATE_FILE.write_text(json.dumps(job, indent=2), encoding="utf-8")


def _clear_job() -> None:
    config.NONAI_JOB_STATE_FILE.unlink(missing_ok=True)


def _attempts_of(source: Path) -> int:
    return _load_attempts().get(relpath(source), 0)


def _bump_attempts(source: Path) -> None:
    attempts = _load_attempts()
    attempts[relpath(source)] = attempts.get(relpath(source), 0) + 1
    _save_attempts(attempts)


def _clear_attempts(source: Path) -> None:
    attempts = _load_attempts()
    if attempts.pop(relpath(source), None) is not None:
        _save_attempts(attempts)


def _load_attempts() -> dict[str, int]:
    try:
        payload = json.loads(config.NONAI_ATTEMPTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_attempts(attempts: dict[str, int]) -> None:
    config.NONAI_ATTEMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.NONAI_ATTEMPTS_FILE.write_text(json.dumps(attempts, indent=2), encoding="utf-8")


def _add_to_skip_manifest(source: Path, reason: str) -> None:
    log.warning("Skipping %s permanently: %s", source, reason)
    with open(config.NONAI_SKIP_MANIFEST, "a", encoding="utf-8") as manifest:
        manifest.write(f"{relpath(source)}\t{reason}\n")


def collect_candidates() -> list[Candidate]:
    """Unprocessed triage-folder videos, most-wanted first."""
    candidates: list[Candidate] = []
    skipped = _skip_manifest_entries()
    watch_scores = _watch_scores()
    for bucket in buckets():
        processed_stems = _processed_stems(bucket)
        for triage_digit, triage_dir in _numbered_dirs(bucket, digits=(0, 1)):
            # Direct children only: a subfolder inside a triage dir stages manual
            # pre-work (e.g. "1_originals_needing_trimming"), so its clips are
            # not ready for an unattended multi-hour encode.
            for video in sorted(triage_dir.iterdir()):
                if not is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
                    continue
                if is_processed_stem(video.stem) or video.stem in processed_stems:
                    continue
                if relpath(video) in skipped:
                    continue
                candidates.append(Candidate(
                    video, bucket, triage_digit, _has_funscript(video),
                    watch_scores.get(str(video).strip().lower(), 0.0),
                ))
    candidates.sort(key=lambda c: (
        c.triage_digit != 1, -c.watch_score, not c.has_funscript, str(c.path).lower(),
    ))
    return candidates


def relpath(video: Path) -> str:
    return video.relative_to(config.NON_AI_DIR).as_posix()


def _numbered_dirs(bucket: Path, digits: tuple[int, ...]) -> list[tuple[int, Path]]:
    """The bucket's triage/stage folders whose names start with one of *digits*."""
    found = []
    for child in sorted(bucket.iterdir()):
        if child.is_dir() and child.name[:1].isdigit() and int(child.name[:1]) in digits:
            found.append((int(child.name[:1]), child))
    return found


def _processed_stems(bucket: Path) -> set[str]:
    """Original stems that already have a processed variant somewhere in *bucket*."""
    stems = set()
    for video in bucket.rglob("*"):
        if is_finalized_video_file(video, config.VIDEO_EXTENSIONS) and is_processed_stem(video.stem):
            stems.add(strip_processing_suffixes(video.stem))
    return stems


def _watch_scores() -> dict[str, float]:
    """Fun Time's per-video watch score, keyed by its normalized path.

    Mirrors the breeding score its playlist weighting uses: completions plus
    three per lock, minus skips. Empty until Fun Time starts tracking primary
    (Nau) plays; satellite entries all point at the AI outbox and simply never
    match a non-AI candidate.
    """
    try:
        payload = json.loads(config.FUN_TIME_WATCH_STATS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: entry.get("completions", 0) + 3 * entry.get("locks", 0) - entry.get("skips", 0)
        for key, entry in payload.items()
        if isinstance(entry, dict)
    }


def _has_funscript(video: Path) -> bool:
    mirrored = config.SCRIPT_LIBRARY_DIR / video.relative_to(config.VIDEO_LIBRARY_DIR)
    return mirrored.with_suffix(config.FUNSCRIPT_EXTENSION).is_file()


def _skip_manifest_entries() -> set[str]:
    try:
        lines = config.NONAI_SKIP_MANIFEST.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.split("\t", 1)[0].strip() for line in lines if line.strip()}
