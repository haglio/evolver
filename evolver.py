#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Invoked by the tray app scheduler or directly via CLI. Stages:
  1. purge      - remove weird outputs and their matching sources
  2. metadata   - scrape AI prompt metadata into mirrored JSON files
  3. sort       - move new videos from inbox into sorted folders by source/orientation
  4. upscale    - apply Topaz frame interpolation + 4x upscale to sorted videos
  5. verify     - check 1_sorted and 2_outbox are in 1-to-1 correspondence
  6. bookmarks  - sync Fun Time favorites into a Chrome bookmarks folder
  7. scripts    - align funscripts to mirror the video library tree
  8. dupes      - scan non_AI for likely duplicate videos by exact filesize
"""

import logging
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import check_correspondence
import check_duplicate_sizes
import config
from tasks import bookmarks_sync, prompt_scrape, purge_weird, scripts_sync, sort, upscale
from util import system_resources


@dataclass
class StageRecord:
    """Result of a single pipeline stage."""
    name: str
    status: str  # "completed", "skipped", "error"
    duration_seconds: float
    result: object | None = None
    skip_reason: str | None = None


@dataclass
class PipelineResult:
    """Aggregate result of all pipeline stages."""
    stages: list[StageRecord] = field(default_factory=list)
    has_errors: bool = False
    duration_seconds: float = 0.0


def setup_logging():
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8")],
    )


def check_dependencies():
    if not config.FFMPEG.is_file():
        raise RuntimeError(f"Topaz ffmpeg not found: {config.FFMPEG}")
    if subprocess.run(["ffprobe", "-version"], capture_output=True).returncode != 0:
        raise RuntimeError("ffprobe not found in PATH")


def run_pipeline(
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
) -> PipelineResult:
    """Run the full evolver pipeline, optionally reporting progress via callbacks.

    Args:
        on_stage_start: Called with (stage_name) before each stage runs.
        on_stage_complete: Called with (stage_name, result, elapsed_seconds, status)
            after each stage. status is "completed", "skipped", or "error".

    Returns:
        PipelineResult with per-stage records and aggregate status.
    """
    log = logging.getLogger(__name__)
    pipeline_t0 = time.monotonic()
    stages: list[StageRecord] = []

    def _run_stage(name, fn, **kwargs):
        if on_stage_start:
            on_stage_start(name)
        t0 = time.monotonic()
        result = fn(**kwargs)
        elapsed = time.monotonic() - t0
        record = StageRecord(name, "completed", elapsed, result)
        stages.append(record)
        if on_stage_complete:
            on_stage_complete(name, result, elapsed, "completed")
        log.info("")
        return result

    def _skip_stage(name, reason):
        if on_stage_start:
            on_stage_start(name)
        record = StageRecord(name, "skipped", 0.0, skip_reason=reason)
        stages.append(record)
        if on_stage_complete:
            on_stage_complete(name, None, 0.0, "skipped")

    purge_result = _run_stage("purge", purge_weird.run)
    prompt_scrape_result = _run_stage("metadata", prompt_scrape.run)
    sort_result = _run_stage("sort", sort.run)

    priority_files = getattr(sort_result, "moved_files", [])
    upscale_result = None
    upscale_skipped = False
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending upscale work found. Skipping upscale.")
        _skip_stage("upscale", "no_pending_work")
    elif _should_skip_upscale_due_to_cpu(log):
        log.info("Skipping upscale because CPU usage is above the configured threshold.")
        upscale_skipped = True
        _skip_stage("upscale", "cpu_busy")
    else:
        upscale_kwargs: dict = dict(
            priority_files=priority_files, max_items=config.UPSCALE_BATCH_LIMIT,
        )
        if on_stage_progress is not None:
            upscale_kwargs["on_progress"] = lambda cur, tot: on_stage_progress("upscale", cur, tot)
        upscale_result = _run_stage("upscale", upscale.run, **upscale_kwargs)

    upscale_still_pending = (
        upscale_skipped
        or (upscale_result is not None and upscale_result.pending_after_run > 0)
    )
    if upscale_still_pending:
        log.info("Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
        correspondence_result = check_correspondence.CorrespondenceResult(sorted_count=0, outbox_count=0)
        _skip_stage("verify", "upscale_pending")
    else:
        correspondence_result = _run_stage("verify", check_correspondence.run, show_popup=True)

    bookmarks_sync_result = _run_stage("bookmarks", bookmarks_sync.run)
    scripts_sync_result = _run_stage("scripts", scripts_sync.run, show_popup=True)
    duplicate_sizes_result = _run_stage("dupes", check_duplicate_sizes.run, show_popup=True)

    has_errors = (
        bool(purge_result.missing_sorted)
        or not prompt_scrape_result.ok
        or not correspondence_result.ok
        or not bookmarks_sync_result.ok
        or not scripts_sync_result.ok
        or not duplicate_sizes_result.ok
    )
    if upscale_result is not None:
        has_errors = has_errors or upscale_result.failed > 0 or upscale_result.deferred_low_disk

    return PipelineResult(
        stages=stages,
        has_errors=has_errors,
        duration_seconds=time.monotonic() - pipeline_t0,
    )


def main():
    setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_dependencies()
    except RuntimeError as e:
        log.error("Dependency check failed: %s", e)
        sys.exit(1)

    result = run_pipeline()
    sys.exit(1 if result.has_errors else 0)


def _should_skip_upscale_due_to_cpu(log: logging.Logger) -> bool:
    if not config.ENABLE_CPU_BUSY_SKIP:
        return False
    try:
        busy_percent = system_resources.cpu_busy_percent(config.CPU_BUSY_SKIP_SAMPLE_SECONDS)
    except Exception:
        log.exception("CPU usage probe failed; proceeding with Stage 4.")
        return False

    log.info(
        "CPU busy sample: %.1f%% (threshold %.1f%%)",
        busy_percent,
        config.CPU_BUSY_SKIP_THRESHOLD_PCT,
    )
    return busy_percent >= config.CPU_BUSY_SKIP_THRESHOLD_PCT




if __name__ == "__main__":
    main()
