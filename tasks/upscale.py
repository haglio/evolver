"""Upscale videos from 1_sorted/<source>/<orientation>/ using Topaz."""

import json
import logging
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import config
from util import system_resources, topaz
from util.media_files import is_finalized_video_file, iter_finalized_videos, remove_partial_video_files
from util.sidecar import sidecar_path, upscaled_video_path
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class UpscaleResult:
    processed: int = 0
    failed: int = 0
    timed_out: int = 0
    deferred_low_disk: bool = False
    pending_after_run: int = 0


def run(priority_files: list[Path] | None = None, max_items: int | None = None,
        on_progress: Callable[[int, int], None] | None = None) -> UpscaleResult:
    result = UpscaleResult()
    max_items = config.UPSCALE_BATCH_LIMIT if max_items is None else max_items
    run_budget_seconds = max(config.UPSCALE_RUN_BUDGET_SECONDS, 0)
    min_start_remaining_seconds = max(config.UPSCALE_MIN_START_REMAINING_SECONDS, 0)
    started_at = time.monotonic()

    for orient in ("landscape", "portrait"):
        (config.OUT_UPSCALED_DIR / orient).mkdir(parents=True, exist_ok=True)
    config.WEIRD_DIR.mkdir(parents=True, exist_ok=True)
    removed_partial_outputs = remove_partial_video_files(config.OUT_UPSCALED_DIR, config.VIDEO_EXTENSIONS, logger=log)

    log.info("=== Stage: upscale from 1_sorted ===")
    log.info("OUT: %s/{landscape,portrait}/<source>/", config.OUT_UPSCALED_DIR)
    log.info("Also skip if exists in: %s", config.WEIRD_DIR)
    if removed_partial_outputs:
        log.info("Removed %d stale partial output file(s) from %s", removed_partial_outputs, config.OUT_UPSCALED_DIR)

    env = topaz.environment()
    candidates = collect_candidates(priority_files=priority_files)
    total_pending = len(candidates)
    if max_items is not None:
        candidates = candidates[:max_items]
    log.info(
        "Queued %d pending video(s); processing up to %d this run (budget %.1f min, keep %.1f min buffer)",
        total_pending,
        len(candidates),
        run_budget_seconds / 60 if run_budget_seconds else 0,
        min_start_remaining_seconds / 60 if min_start_remaining_seconds else 0,
    )

    for in_file, source, orient in candidates:
        elapsed = time.monotonic() - started_at
        remaining_budget = run_budget_seconds - elapsed
        if run_budget_seconds and (result.processed or result.failed) and remaining_budget < min_start_remaining_seconds:
            log.info(
                "Stopping the upscale stage before starting another video to stay under the run budget "
                "(elapsed %.1f min, remaining %.1f min).",
                elapsed / 60,
                max(remaining_budget, 0) / 60,
            )
            break

        if _is_low_disk():
            result.deferred_low_disk = True
            result.pending_after_run = total_pending - result.processed - result.failed
            _show_low_disk_warning()
            log.warning("Stopping the upscale stage early due to low free disk space.")
            break

        out = upscaled_video_path(source, orient, in_file.stem)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{in_file.stem}.partial.{uuid.uuid4().hex}.mp4")

        log.info("Process: %s -> %s  [%s/%s]", in_file.name, out.name, orient, source)

        if _is_t2v_provider(source, orient, in_file.stem):
            filter_complex = config.UPSCALE_FILTER_T2V_provider
            videoai_tag = config.VIDEOAI_TAG_T2V_provider
        else:
            filter_complex = config.UPSCALE_FILTER_DEFAULT
            videoai_tag = config.VIDEOAI_TAG_DEFAULT

        ffmpeg_timeout = max(remaining_budget, 1) if run_budget_seconds else None
        ffmpeg_ok = False
        try:
            ffmpeg_ok = _run_ffmpeg(in_file, tmp, env, filter_complex, videoai_tag, timeout=ffmpeg_timeout)
        except subprocess.TimeoutExpired:
            elapsed_at_timeout = time.monotonic() - started_at
            log.info("FAILED (timed out after %.1fs): %s", elapsed_at_timeout, in_file)
            tmp.unlink(missing_ok=True)
            result.timed_out += 1
            result.failed += 1
            if on_progress:
                on_progress(result.processed + result.failed, len(candidates))
            break
        except OSError:
            log.exception("FAILED (ffmpeg launch error): %s", in_file)

        if ffmpeg_ok:
            if tmp.exists() and tmp.stat().st_size > 0:
                try:
                    tmp.replace(out)
                finally:
                    tmp.unlink(missing_ok=True)
                result.processed += 1
                log.info("Wrote: %s", out)
            else:
                tmp.unlink(missing_ok=True)
                result.failed += 1
                log.info("FAILED (empty output): %s", in_file)
        else:
            tmp.unlink(missing_ok=True)
            result.failed += 1
            log.info("FAILED (ffmpeg error): %s", in_file)

        if on_progress:
            on_progress(result.processed + result.failed, len(candidates))

    if not result.deferred_low_disk:
        result.pending_after_run = max(total_pending - result.processed - result.failed, 0)

    log.info("")
    log.info("Done.")
    log.info("Upscaled: %d", result.processed)
    log.info("Failed: %d", result.failed)
    if result.pending_after_run:
        log.info("Pending after this run: %d", result.pending_after_run)
    return result


def has_pending_work(priority_files: list[Path] | None = None) -> bool:
    return bool(collect_candidates(priority_files=priority_files, limit=1))


def collect_candidates(priority_files: list[Path] | None = None, limit: int | None = None) -> list[tuple[Path, str, str]]:
    candidates: list[tuple[Path, str, str]] = []
    seen: set[Path] = set()

    def add_candidate(in_file: Path, source: str, orient: str) -> bool:
        if in_file in seen or not in_file.exists():
            return False
        seen.add(in_file)
        if _already_processed(source, upscaled_video_path(source, orient, in_file.stem).name):
            return False
        candidates.append((in_file, source, orient))
        return True

    for in_file in priority_files or []:
        try:
            rel = in_file.relative_to(config.SORTED_DIR)
        except ValueError:
            continue
        if len(rel.parts) < 3:
            continue
        source, orient = rel.parts[0], rel.parts[1]
        if orient not in ("landscape", "portrait"):
            continue
        if is_finalized_video_file(in_file, config.VIDEO_EXTENSIONS):
            if add_candidate(in_file, source, orient) and limit is not None and len(candidates) >= limit:
                return candidates

    for source in _iter_sources(config.SORTED_DIR):
        for orient in ("landscape", "portrait"):
            in_root = config.SORTED_DIR / source / orient
            if not in_root.is_dir():
                continue
            for in_file in _iter_videos(in_root):
                if add_candidate(in_file, source, orient) and limit is not None and len(candidates) >= limit:
                    return candidates

    return candidates


def _run_ffmpeg(in_file: Path, tmp: Path, env: dict, filter_complex: str, videoai_tag: str, timeout: float | None = None) -> bool:
    return subprocess.run(
        topaz.command(in_file, tmp, filter_complex, videoai_tag), env=env, timeout=timeout,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode == 0


def _is_t2v_provider(source: str, orient: str, stem: str) -> bool:
    if source != "provider":
        return False
    meta_path = sidecar_path(upscaled_video_path(source, orient, stem))
    if not meta_path.is_file():
        return False
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return "source_image" not in payload
    except Exception:
        return False


def _already_processed(source: str, fname: str) -> bool:
    for orient in ("landscape", "portrait"):
        p = config.OUT_UPSCALED_DIR / orient / source / fname
        if p.exists() and p.stat().st_size > 0:
            return True
    weird = config.WEIRD_DIR / fname
    return weird.exists() and weird.stat().st_size > 0


def _is_low_disk() -> bool:
    free_gb = system_resources.free_bytes(config.OUT_UPSCALED_DIR) / (1024 ** 3)
    return free_gb < config.LOW_DISK_WARNING_GB


def _show_low_disk_warning() -> None:
    free_gb = system_resources.free_bytes(config.OUT_UPSCALED_DIR) / (1024 ** 3)
    show_error_window(
        "Evolver - Low Disk Space",
        (
            "Evolver paused the upscale stage because free disk space is below the configured safety floor.\n\n"
            f"Target outbox: {config.OUT_UPSCALED_DIR}\n"
            f"Free space: {free_gb:.1f} GiB\n"
            f"Required floor: {config.LOW_DISK_WARNING_GB:.1f} GiB\n\n"
            f"Check the log for details:\n{config.LOG_FILE}"
        ),
    )


def _iter_videos(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def _iter_sources(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir():
            yield p.name
