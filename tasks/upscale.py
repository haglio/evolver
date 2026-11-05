from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from functools import partial
from pathlib import Path

import config
from util import (
    ffprobe,
    lanes,
    orientation,
    origenerator_gallery,
    provenance,
    sidecar,
    system_resources,
    topaz,
    video_kind,
)
from util.alert import show_error
from util.media_files import (
    child_dirs,
    is_finalized_video_file,
    library_videos,
    partial_path,
    remove_partial_files,
    retry_while_in_use,
    take_its_place,
)
from util.sidecar import sidecar_path, upscaled_video_path

log = logging.getLogger(__name__)

_SORTED_DEPTH = 3


@dataclass
class UpscaleResult:
    processed: int = 0
    failed: int = 0
    stopped_at_budget: int = 0
    deferred_low_disk: bool = False
    pending_after_run: int = 0


@dataclass(frozen=True)
class UpscaleFolders:
    sorted: Path
    outbox: Path
    trash: Path
    origenerator: Path

    @classmethod
    def configured(cls, **given: Path | None) -> UpscaleFolders:
        defaults = {
            "sorted": config.SORTED_DIR,
            "outbox": config.OUT_UPSCALED_DIR,
            "trash": config.TRASH_DIR,
            "origenerator": config.ORIGENERATOR_PROJECT_DIR,
        }
        return cls(**_given_or_configured(given, defaults))


@dataclass(frozen=True)
class LowDiskWarning:
    floor_gb: float
    dismissed_file: Path

    @classmethod
    def configured(cls, **given: float | Path | None) -> LowDiskWarning:
        defaults = {
            "floor_gb": config.LOW_DISK_WARNING_GB,
            "dismissed_file": config.LOW_DISK_WARNING_DISMISSED_FILE,
        }
        return cls(**_given_or_configured(given, defaults))


@dataclass(frozen=True)
class Listeners:
    on_progress: Callable[[int, int], None] = lambda done, queued: None
    on_filed: Callable[[str], None] = lambda source: None


def _given_or_configured(given: dict, defaults: dict) -> dict:
    unknown = given.keys() - defaults.keys()
    if unknown:
        raise TypeError(f"unknown setting: {', '.join(sorted(unknown))}")
    return {name: default if given.get(name) is None else given[name]
            for name, default in defaults.items()}


class _Outcome(Enum):
    UPSCALED = auto()
    FAILED = auto()
    BUDGET_SPENT = auto()


@dataclass(frozen=True)
class _Budget:
    run_seconds: float
    min_start_remaining_seconds: float
    started_at: float

    @classmethod
    def starting_now(cls) -> _Budget:
        return cls(max(config.UPSCALE_RUN_BUDGET_SECONDS, 0),
                   max(config.UPSCALE_MIN_START_REMAINING_SECONDS, 0), time.monotonic())

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining(self) -> float:
        return self.run_seconds - self.elapsed()

    def too_little_left_for_another(self, already_worked: bool) -> bool:
        return bool(self.run_seconds and already_worked
                    and self.remaining() < self.min_start_remaining_seconds)

    def encode_timeout(self) -> float | None:
        return max(self.remaining(), 1) if self.run_seconds else None


def run(
    *,
    priority_files: list[Path] | None = None,
    max_items: int | None = None,
    listeners: Listeners | None = None,
    folders: UpscaleFolders | None = None,
    low_disk: LowDiskWarning | None = None,
) -> UpscaleResult:
    listeners = Listeners() if listeners is None else listeners
    folders = UpscaleFolders.configured() if folders is None else folders
    low_disk = LowDiskWarning.configured() if low_disk is None else low_disk
    result = UpscaleResult()
    max_items = config.UPSCALE_BATCH_LIMIT if max_items is None else max_items
    budget = _Budget.starting_now()

    _prepare_outbox(folders, low_disk)

    env = topaz.environment()
    candidates = collect_queued_videos(
        priority_files=priority_files,
        sorted_dir=folders.sorted, outbox_dir=folders.outbox, trash_dir=folders.trash,
    )
    total_pending = len(candidates)
    if max_items is not None:
        candidates = candidates[:max_items]
    log.info(
        "Queued %d pending video(s); processing up to %d this run (budget %.1f min, keep %.1f min buffer)",
        total_pending,
        len(candidates),
        budget.run_seconds / 60 if budget.run_seconds else 0,
        budget.min_start_remaining_seconds / 60 if budget.min_start_remaining_seconds else 0,
    )

    for candidate in candidates:
        if budget.too_little_left_for_another(bool(result.processed or result.failed)):
            log.info(
                "Stopping the upscale stage before starting another video to stay under the run budget "
                "(elapsed %.1f min, remaining %.1f min).",
                budget.elapsed() / 60,
                max(budget.remaining(), 0) / 60,
            )
            break

        if system_resources.free_gb(folders.outbox) < low_disk.floor_gb:
            result.deferred_low_disk = True
            result.pending_after_run = total_pending - result.processed - result.failed
            _show_low_disk_warning(folders.outbox, low_disk.floor_gb, low_disk.dismissed_file)
            log.warning("Stopping the upscale stage early due to low free disk space.")
            break

        outcome = _upscale_one(candidate, env, folders, budget)
        if outcome is _Outcome.UPSCALED:
            result.processed += 1
            listeners.on_filed(candidate[1])
        elif outcome is _Outcome.FAILED:
            result.failed += 1
        else:
            result.stopped_at_budget += 1
        listeners.on_progress(result.processed + result.failed, len(candidates))
        if outcome is _Outcome.BUDGET_SPENT:
            break

    if not result.deferred_low_disk:
        result.pending_after_run = max(total_pending - result.processed - result.failed, 0)

    log.info("")
    log.info("Done.")
    log.info("Upscaled: %d", result.processed)
    log.info("Failed: %d", result.failed)
    if result.pending_after_run:
        log.info("Pending after this run: %d", result.pending_after_run)
    return result


def _prepare_outbox(folders: UpscaleFolders, low_disk: LowDiskWarning):
    for orient in orientation.SORTED:
        (folders.outbox / orient).mkdir(parents=True, exist_ok=True)
    folders.trash.mkdir(parents=True, exist_ok=True)
    removed_partial_outputs = remove_partial_files(folders.outbox, logger=log)
    if system_resources.free_gb(folders.outbox) >= low_disk.floor_gb:
        _bring_back_the_low_disk_warning(low_disk.dismissed_file)

    log.info("=== Stage: upscale from 1_sorted ===")
    log.info("OUT: %s/{landscape,portrait}/<source>/", folders.outbox)
    log.info("Also skip if exists in: %s", folders.trash)
    if removed_partial_outputs:
        log.info("Removed %d stale partial output file(s) from %s",
                 removed_partial_outputs, folders.outbox)


def _upscale_one(candidate: tuple[Path, str, str], env: dict,
                 folders: UpscaleFolders, budget: _Budget) -> _Outcome:
    in_file, source, orient = candidate
    out = upscaled_video_path(source, orient, in_file.stem, folders.outbox)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(out, in_file.stem)

    log.info("Process: %s -> %s  [%s/%s]", in_file.name, out.name, orient, source)

    settings = _settings_for(in_file, source, orient, folders.outbox, folders.origenerator)

    ffmpeg_ok = False
    try:
        ffmpeg_ok = _run_ffmpeg(in_file, tmp, env, settings, timeout=budget.encode_timeout())
    except subprocess.TimeoutExpired:
        log.info(
            "Run budget spent after %.1fs; stopped this encode and left the video queued: %s",
            budget.elapsed(), in_file,
        )
        tmp.unlink(missing_ok=True)
        return _Outcome.BUDGET_SPENT
    except OSError:
        log.exception("FAILED (ffmpeg launch error): %s", in_file)

    if not ffmpeg_ok:
        tmp.unlink(missing_ok=True)
        log.info("FAILED (ffmpeg error): %s", in_file)
        return _Outcome.FAILED
    return _promote_the_output(in_file, tmp, out, settings)


def _promote_the_output(in_file: Path, tmp: Path, out: Path,
                        settings: topaz.Settings) -> _Outcome:
    if not (tmp.exists() and tmp.stat().st_size > 0):
        tmp.unlink(missing_ok=True)
        log.info("FAILED (empty output): %s", in_file)
        return _Outcome.FAILED
    try:
        retry_while_in_use(partial(take_its_place, tmp, out))
    except OSError:
        log.info("FAILED (a player still holds the upscale it replaces): %s", out)
        return _Outcome.FAILED
    else:
        log.info("Wrote: %s", out)
        _record_the_upscale(out, settings)
        return _Outcome.UPSCALED
    finally:
        tmp.unlink(missing_ok=True)


def has_pending_work(priority_files: list[Path] | None = None) -> bool:
    return bool(collect_queued_videos(priority_files=priority_files, limit=1))


def collect_queued_videos(
    priority_files: list[Path] | None = None,
    limit: int | None = None,
    *,
    sorted_dir: Path | None = None,
    outbox_dir: Path | None = None,
    trash_dir: Path | None = None,
) -> list[tuple[Path, str, str]]:
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    outbox_dir = config.OUT_UPSCALED_DIR if outbox_dir is None else outbox_dir
    trash_dir = config.TRASH_DIR if trash_dir is None else trash_dir

    candidates: list[tuple[Path, str, str]] = []
    remakes: list[tuple[Path, str, str]] = []
    seen: set[Path] = set()

    def add_candidate(in_file: Path, source: str, orient: str) -> bool:
        if in_file in seen or not in_file.exists():
            return False
        seen.add(in_file)
        out = upscaled_video_path(source, orient, in_file.stem, outbox_dir)
        if _already_processed(source, out.name, outbox_dir, trash_dir):
            if out.is_file() and _made_by_superseded_settings(source, out):
                remakes.append((in_file, source, orient))
            return False
        candidates.append((in_file, source, orient))
        return True

    for in_file in priority_files or []:
        try:
            rel = in_file.relative_to(sorted_dir)
        except ValueError:
            continue
        if len(rel.parts) < _SORTED_DEPTH:
            continue
        source, orient = rel.parts[0], rel.parts[1]
        if orient not in orientation.SORTED:
            continue
        if (is_finalized_video_file(in_file)
                and add_candidate(in_file, source, orient)
                and limit is not None
                and len(candidates) >= limit):
            return candidates

    for source_dir in child_dirs(sorted_dir):
        source = source_dir.name
        for orient in orientation.SORTED:
            in_root = sorted_dir / source / orient
            if not in_root.is_dir():
                continue
            for in_file in library_videos(in_root):
                if add_candidate(in_file, source, orient) and limit is not None and len(candidates) >= limit:
                    return candidates

    pending = candidates + remakes
    return pending if limit is None else pending[:limit]


def _run_ffmpeg(in_file: Path, tmp: Path, env: dict, settings: topaz.Settings,
                timeout: float | None = None) -> bool:
    return subprocess.run(
        topaz.command(in_file, tmp, settings), env=env, timeout=timeout,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode == 0


def _made_by_superseded_settings(source: str, upscaled: Path) -> bool:
    if not lanes.sent_by_origenerator(source):
        return False
    try:
        payload = sidecar.read(sidecar_path(upscaled))
    except ValueError:
        return False
    made_by = provenance.stamps_of(payload).get(provenance.UPSCALE) or {}
    current = topaz.AI_UPSCALE_ORIGENERATOR
    return (made_by.get(provenance.METHOD), made_by.get(provenance.METHOD_VERSION)) != (current.name, current.version)


def _settings_for(in_file: Path, source: str, orient: str, outbox_dir: Path,
                origenerator_dir: Path) -> topaz.Settings:
    if lanes.sent_by_origenerator(source):
        return topaz.framed(topaz.AI_UPSCALE_ORIGENERATOR, orient,
                            video_fps=ffprobe.frame_rate(in_file),
                            generated_fps=origenerator_gallery.generated_fps(origenerator_dir))
    if _is_t2v_provider(source, orient, in_file.stem, outbox_dir):
        return topaz.AI_UPSCALE_T2V
    return topaz.AI_UPSCALE


def _record_the_upscale(out: Path, settings: topaz.Settings) -> None:
    try:
        path = sidecar_path(out)
    except ValueError:
        return
    stamp = provenance.by_evolver(method=settings.name, method_version=settings.version)
    sidecar.update(path, lambda current: provenance.recorded(current, provenance.UPSCALE, stamp))


def _is_t2v_provider(source: str, orient: str, stem: str, outbox_dir: Path) -> bool:
    if source != config.PROVIDER_SOURCE:
        return False
    try:
        meta_path = sidecar_path(upscaled_video_path(source, orient, stem, outbox_dir))
    except ValueError:
        return False
    payload = sidecar.read(meta_path)
    if not payload or video_kind.only_the_video_itself(payload):
        return False
    return "source_image" not in payload


def _already_processed(source: str, fname: str, outbox_dir: Path, trash_dir: Path) -> bool:
    for orient in orientation.SORTED:
        p = outbox_dir / orient / source / fname
        if p.exists() and p.stat().st_size > 0:
            return True
    trash = trash_dir / fname
    return trash.exists() and trash.stat().st_size > 0


def _show_low_disk_warning(outbox_dir: Path, floor_gb: float, dismissed: Path) -> None:
    if dismissed.exists():
        return
    free_gb = system_resources.free_gb(outbox_dir)
    clicked_dismiss = show_error(
        "Evolver - Low Disk Space",
        (
            "Evolver paused the upscale stage because free disk space is below the configured safety floor.\n\n"
            f"Target outbox: {outbox_dir}\n"
            f"Free space: {free_gb:.1f} GiB\n"
            f"Required floor: {floor_gb:.1f} GiB\n\n"
            f"Check the log for details:\n{config.LOG_FILE}"
        ),
        dismissible=True,
    )
    if clicked_dismiss:
        dismissed.parent.mkdir(parents=True, exist_ok=True)
        dismissed.touch()
        log.info("The low-disk warning was dismissed until a run finds room on the drive again.")


def _bring_back_the_low_disk_warning(dismissed: Path) -> None:
    try:
        dismissed.unlink()
    except FileNotFoundError:
        return
    log.info("The drive has room again, so the low-disk warning will show the next time it runs low.")
