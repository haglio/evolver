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
:mod:`tasks.nonai_queue`'s; what is left here is the stage: repair, supervise,
maybe start, report.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import config
from tasks.nonai_queue import Candidate, add_to_skip_manifest, collect_candidates, relpath
from util import (
    ffprobe,
    funscript,
    nonai_job,
    processes,
    sidecar,
    system_resources,
    topaz,
)
from util.media_files import is_finalized_video_file, is_partial_video_path
from util.nonai_library import bucket_of, buckets, stage_dirs
from util.variants import is_processed_stem, strip_processing_suffixes

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
    deferred_low_disk: bool = False
    # Upscales promoted before their sidecar was carried across, handed it back
    # off the retired original — see :func:`repair_retired_metadata`.
    repaired_sidecars: int = 0


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

    The six files the stage touches are resolved here rather than read where
    they are used, so everything below is handed the paths it works on: three
    it writes (the job record, the attempt counter, the cooldown stamp) and
    three the queue reads (the skip and pin manifests, and Fun Time's watch
    stats). They are sentinels rather than signature defaults on purpose: a
    default is evaluated at import, which would freeze whatever ``config`` held
    then and put the value out of reach of ``override_config``, the seam the
    stage's tests steer it with.
    """
    job_file = config.NONAI_JOB_STATE_FILE if job_file is None else job_file
    attempts_file = config.NONAI_ATTEMPTS_FILE if attempts_file is None else attempts_file
    cooldown_file = config.NONAI_COOLDOWN_FILE if cooldown_file is None else cooldown_file
    skip_manifest = config.NONAI_SKIP_MANIFEST if skip_manifest is None else skip_manifest
    pin_manifest = config.NONAI_PRIORITY_MANIFEST if pin_manifest is None else pin_manifest
    watch_stats_file = (config.FUN_TIME_WATCH_STATS_FILE if watch_stats_file is None
                        else watch_stats_file)
    result = NonAiUpscaleResult()
    log.info("=== Stage: upscale non-AI library ===")

    repair_retired_metadata(result)

    with _throttle_lock:
        job = nonai_job.load_job(job_file)
        if job is None:
            job = _adopt_orphan(job_file)
        _sweep_orphaned_partials(keep=Path(job["tmp"]) if job and "tmp" in job else None)
        if job is not None:
            _supervise(job, result, job_file=job_file, attempts_file=attempts_file,
                       cooldown_file=cooldown_file, skip_manifest=skip_manifest,
                       stop=stop, presence_managed=presence_managed)

        if not result.in_flight and allow_start and not stop:
            _start_next_candidate(result, job_file=job_file,
                                  attempts_file=attempts_file,
                                  cooldown_file=cooldown_file,
                                  skip_manifest=skip_manifest,
                                  pin_manifest=pin_manifest,
                                  watch_stats_file=watch_stats_file)

    # Collected a second time on purpose: a start attempt can retire clips to
    # the skip manifest, and the count reported is the queue as it stands after
    # that. The doubled walk is finding tasks/design/008's; merging the two
    # would change what `pending` means, so it stays and stays visible.
    result.pending = len(collect_candidates(
        skip_manifest=skip_manifest, pin_manifest=pin_manifest,
        watch_stats_file=watch_stats_file))
    in_flight = result.in_flight or "-"
    if result.in_flight and result.in_flight_percent is not None:
        in_flight = f"{result.in_flight} ({result.in_flight_percent}% encoded)"
    if result.in_flight and result.suspended:
        in_flight = f"{in_flight} [suspended: user present]"
    log.info(
        "Non-AI upscale: started=%s in_flight=%s promoted=%s stopped=%s deferred=%s "
        "failed=%s pending=%d repaired=%d sidecar(s)",
        result.started or "-", in_flight, result.promoted or "-",
        result.stopped or "-", result.start_deferred or "-",
        result.failed or "-", result.pending, result.repaired_sidecars,
    )
    return result


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
            _suspend_job(job, job_file)
            return "suspended"
        if not present and job.get("suspended"):
            _resume_job(job, job_file)
            return "resumed"
        return ""


def _adopt_orphan(job_file: Path) -> dict | None:
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


def _supervise(job: dict, result: NonAiUpscaleResult, *, job_file: Path,
               attempts_file: Path, cooldown_file: Path, skip_manifest: Path,
               stop: bool = False, presence_managed: bool = False) -> None:
    pid = job.get("pid", 0)
    source = Path(job.get("source", ""))
    if pid and processes.is_running(pid):
        if stop:
            _stop_in_flight(job, result, "the non-AI upscale toggle is off",
                            job_file=job_file, attempts_file=attempts_file)
            return
        if _is_low_disk():
            # The 250 GB floor was clear at start, but a 4K60 output plus
            # whatever else writes overnight can cross it mid-encode.
            result.deferred_low_disk = True
            _stop_in_flight(job, result,
                            "free disk fell below the safety floor mid-encode",
                            job_file=job_file, attempts_file=attempts_file)
            return
        if presence_managed and _user_present():
            _suspend_job(job, job_file)
            result.in_flight = relpath(source)
            result.in_flight_percent = _percent_encoded(job)
            result.suspended = True
            return
        if presence_managed:
            _resume_job(job, job_file)  # a no-op unless it was frozen
        if not _overran(job):
            result.in_flight = relpath(source)
            result.in_flight_percent = _percent_encoded(job)
            return
        _terminate_ffmpeg(pid, f"it exceeded the {config.NONAI_MAX_RUNTIME_HOURS}h runtime cap")
    _conclude(job, result, attempts_file=attempts_file, cooldown_file=cooldown_file,
              skip_manifest=skip_manifest)
    nonai_job.clear_job(job_file)


def _suspend_job(job: dict, job_file: Path) -> None:
    """Freeze the encode and remember when, so the pause is not charged runtime."""
    if job.get("suspended"):
        return
    processes.suspend(job.get("pid", 0))
    job["suspended"] = True
    job["suspended_at"] = time.time()
    nonai_job.save_job(job_file, job)
    log.info("Suspended the non-AI encode of %s; the user is back at the machine.",
             job.get("source"))


def _resume_job(job: dict, job_file: Path) -> None:
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


def _stop_in_flight(job: dict, result: NonAiUpscaleResult, reason: str, *,
                    job_file: Path, attempts_file: Path) -> None:
    """End the encode through no fault of its video — no retry penalty."""
    source = Path(job.get("source", ""))
    _terminate_ffmpeg(job.get("pid", 0), reason)
    _delete_tmp(Path(job.get("tmp", "")))
    nonai_job.clear_attempts(attempts_file, relpath(source))
    nonai_job.clear_job(job_file)
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


def _conclude(job: dict, result: NonAiUpscaleResult, *, attempts_file: Path,
              cooldown_file: Path, skip_manifest: Path) -> None:
    source = Path(job.get("source", ""))
    tmp = Path(job.get("tmp", ""))
    out = Path(job.get("out", ""))
    expected = job.get("expected_duration") or 0.0
    actual = ffprobe.duration_seconds(tmp) if tmp.is_file() else None

    nonai_job.stamp_encode_ended(cooldown_file)
    if actual and expected and actual >= config.NONAI_COMPLETE_DURATION_FRACTION * expected:
        tmp.replace(out)
        # Before the original leaves, and it takes its sidecar with it.
        _carry_metadata(source, out)
        _retire_original(source)
        nonai_job.clear_attempts(attempts_file, relpath(source))
        result.promoted = relpath(source)
        log.info("Promoted finished non-AI upscale: %s", out)
        return

    result.failed = relpath(source)
    log.error("Non-AI upscale did not complete (%s): output covers %s of expected %.1fs.",
              source, f"{actual:.1f}s" if actual else "none", expected)
    _delete_tmp(tmp)
    if nonai_job.attempts_of(attempts_file, relpath(source)) >= config.NONAI_MAX_ATTEMPTS:
        add_to_skip_manifest(skip_manifest, source,
                             f"failed {config.NONAI_MAX_ATTEMPTS} attempts")
        nonai_job.clear_attempts(attempts_file, relpath(source))


def _delete_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        # A just-killed ffmpeg can briefly hold the file; the partial sweep
        # removes it on a later tick.
        log.exception("Could not delete partial output %s yet.", tmp)


# The one part of a sidecar that describes the FILE rather than the footage in
# it: which family it belongs to and whether it is a processed variant.  An
# upscale's is its own, and the grouping stage stamps it on the same pass.
_FILE_SCOPED_SIDECAR_KEYS = frozenset({"version"})


def _sidecar_beside_or_mirrored(video: Path) -> Path:
    """Where *video*'s sidecar lives: mirrored under ``METADATA_DIR``, or beside it.

    The metadata tree mirrors the library and nothing else, so a retired original
    that has left the library keeps its own copy next to the video instead (see
    :func:`_archive_original`).  Asking the mirror where that is computes a path
    under a tree the video is not in, which is the ``ValueError`` here — the
    archive is the only thing outside the library this stage ever reads.
    """
    try:
        return sidecar.sidecar_path(video)
    except ValueError:
        return video.with_suffix(".json")


def _carry_metadata(source: Path, out: Path) -> bool:
    """Give *out* what *source*'s sidecar says about the footage they share.

    An upscale IS its original's footage, so the ``clip`` object naming which
    compilation the video was carved out of, and the act recorded on it,
    describe the upscale exactly as well.  They lived only on the original,
    though, and retirement takes its sidecar out of the library — so unless the
    upscale is handed its own copy first, promoting it is what loses them.

    Nothing downstream puts them back.  The grouping stage would copy a ``clip``
    across from an in-library original, but it runs later in the same pass and
    by then there is none.  So without this the upscale reaches the library with
    nothing to say it was ever a cut.

    Funscripts are deliberately not carried: :mod:`tasks.scripts_sync` already
    copies an original's script onto its processed variants, and a second thing
    writing scripts is a second thing to disagree with it.
    """
    payload = sidecar.read(_sidecar_beside_or_mirrored(source))
    carried = {
        key: value for key, value in payload.items()
        if key not in _FILE_SCOPED_SIDECAR_KEYS
    }
    if not carried:
        return False
    destination = _sidecar_beside_or_mirrored(out)
    existing = sidecar.read(destination)
    merged = {**existing, **carried}
    if merged == existing:
        return False
    sidecar.write(destination, merged)
    log.info("Carried metadata onto upscale: %s -> %s", source.name, out.name)
    return True


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
            original = _archived_original(archived, strip_processing_suffixes(video.stem))
            if original is None:
                continue
            result.repaired_sidecars += int(_carry_metadata(original, video))


def _archived_original(archived: Path, stem: str) -> Path | None:
    """The retired original named *stem* under *archived*, if exactly one is.

    The archive mirrors the library path an original was retired FROM, which is
    a triage folder rather than the ``3*/processed/`` the upscale now sits in,
    so it is found by name within the bucket rather than at a computed path.
    Two of a name is not a tie to break: nothing here can say which of them the
    upscale came from, and guessing would write one clip's provenance onto
    another's footage.

    Matched by comparing stems rather than by globbing one: a title is free to
    hold the characters a glob reserves, and ``[Studio] scene one`` read as a
    pattern is a character class that matches none of its own name.
    """
    matches = sorted(
        path for path in archived.rglob("*")
        if path.stem == stem and is_finalized_video_file(path, config.VIDEO_EXTENSIONS)
    )
    if len(matches) == 1:
        return matches[0]
    if matches:
        log.warning("Ambiguous archived original for %s: %d matches, leaving it alone.",
                    stem, len(matches))
    return None


def _retire_original(source: Path) -> None:
    """Move the superseded original out of the way, now that its upscale exists.

    Into the bucket's ``2*`` folder, as the user does by hand — or, when
    ``config.NONAI_RETIRED_ROOT`` names an archive, out of the library
    altogether, because that folder is on the drive the encodes fill.
    """
    if config.NONAI_RETIRED_ROOT is not None:
        _archive_original(source)
        return
    bucket = bucket_of(source)
    retire_dirs = stage_dirs(bucket, digits=(2,)) if bucket else []
    if not retire_dirs:
        log.warning("No '2*' folder in %s; leaving the original at %s.", bucket, source)
        return
    dest = retire_dirs[0][1] / source.name
    if dest.exists():
        log.warning("Original collides with %s; leaving it at %s.", dest, source)
        return
    source.replace(dest)
    _move_mirrored_files(source, dest)
    log.info("Retired original: %s -> %s", source, dest)


def _archive_original(source: Path) -> None:
    """Move *source* out of the library, under the archive at its library path.

    Its sidecar and funscript come along and sit beside it rather than in the
    mirrored trees, which only cover the library: an archived video is a cold
    copy that has to describe itself. Leaving the funscript behind is the worse
    half — it still matches the video by name, so the scripts sync would try to
    relocate it onto a destination the clip-scripts stage has already written,
    and fail the run on a collision nothing can resolve.
    """
    dest = config.NONAI_RETIRED_ROOT / source.relative_to(config.NON_AI_DIR)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for mirrored_path, suffix in (
        (sidecar.sidecar_path, ".json"),
        (funscript.script_path_for_video, config.FUNSCRIPT_EXTENSION),
    ):
        src = mirrored_path(source)
        if src.exists():
            shutil.move(str(src), str(dest.with_suffix(suffix)))
    shutil.move(str(source), str(dest))
    log.info("Archived original: %s -> %s", source, dest)


def _move_mirrored_files(source: Path, dest: Path) -> None:
    """Carry a retired original's sidecar and funscript to its new path.

    The metadata and script trees both mirror the video tree, so both of a
    moved video's files must move with it. A left-behind sidecar is orphaned
    and pruned, losing the ``clip`` family metadata Nau navigates by (the
    grouping stage re-stamps ``version`` on the next run; this keeps
    ``clip``/``video`` from vanishing). A left-behind funscript is worse than
    orphaned: the scripts sync would relocate it, but the clip-scripts stage
    runs first and writes the clip a fresh script at the new path, so the sync
    finds its destination taken and fails the run on an unresolvable collision.
    """
    for mirrored_path in (sidecar.sidecar_path, funscript.script_path_for_video):
        src = mirrored_path(source)
        if not src.exists():
            continue
        dst = mirrored_path(dest)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)


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


def _start_next_candidate(result: NonAiUpscaleResult, *, job_file: Path,
                          attempts_file: Path, cooldown_file: Path,
                          skip_manifest: Path, pin_manifest: Path,
                          watch_stats_file: Path) -> None:
    if _is_low_disk():
        result.deferred_low_disk = True
        log.warning("Deferring non-AI upscale start: free disk is below the safety floor.")
        return
    result.start_deferred = _machine_busy_reason(cooldown_file)
    if result.start_deferred:
        log.info("Deferring non-AI upscale start: %s.", result.start_deferred)
        return

    for candidate in collect_candidates(skip_manifest=skip_manifest,
                                        pin_manifest=pin_manifest,
                                        watch_stats_file=watch_stats_file):
        source = candidate.path
        expected_duration = ffprobe.duration_seconds(source)
        orientation = ffprobe.get_orientation(source)
        if ffprobe.videoai_tag(source):
            add_to_skip_manifest(skip_manifest, source,
                                 "already carries a Topaz videoai tag")
            continue
        if expected_duration is None or orientation == "unknown":
            add_to_skip_manifest(skip_manifest, source,
                                 "ffprobe could not read duration or orientation")
            continue

        out = _output_path(candidate)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{source.stem}.partial.{uuid.uuid4().hex}.mp4")
        nonai_job.bump_attempts(attempts_file, relpath(source))
        pid = _launch(source, tmp, orientation)
        nonai_job.save_job(job_file, {
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
