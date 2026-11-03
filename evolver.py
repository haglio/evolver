from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app_support.subprocess_utils import hidden_subprocess_kwargs

import check_correspondence
import check_duplicate_sizes
import config
from tasks import (
    bookmarks_sync,
    clip_scripts,
    genau_deliver,
    nonai_group,
    nonai_queue,
    nonai_request,
    nonai_titles,
    nonai_upscale,
    nonai_upscale_queue,
    origenerator_downtime,
    prompt_scrape,
    provenance_sweep,
    reference_sync,
    scene_scripts,
    scripts_sync,
    sort,
    stray_files,
    taken_back,
    upscale,
    video_kinds,
    watch_weights,
)
from util import run_lock, run_log, system_resources, topaz
from util import upscale_queue as upscale_queue_shape


@dataclass
class StageRecord:
    name: str
    status: str
    duration_seconds: float
    result: object | None = None
    skip_reason: str | None = None


_STAGE_FAILED: dict[str, Callable[[object], bool]] = {
    "metadata": lambda r: not r.ok,
    "upscale": lambda r: bool(r.failed),
    "upscale_non_ai": lambda r: bool(r.failed),
    "genau_deliver": lambda r: bool(r.failed),
    "withdrawn": lambda r: bool(r.failed),
    "origenerator_downtime": lambda r: r.failed,
    "verify": lambda r: not r.ok,
    "references": lambda r: not r.ok,
    "watch_weights": lambda r: not r.ok,
    "bookmarks": lambda r: not r.ok,
    "scripts": lambda r: not r.ok,
    "dupes": lambda r: not r.ok,
}

_STAGE_WARNED: dict[str, Callable[[object], bool]] = {
    "strays": lambda r: not r.ok,
    "scripts": lambda r: bool(r.not_checked),
    "references": lambda r: r.needs_an_eye,
    "upscale": lambda r: r.deferred_low_disk,
    "upscale_non_ai": lambda r: r.deferred_low_disk or bool(r.unreachable_archive),
}


def _stage_status(name: str, result: object) -> str:
    failed = _STAGE_FAILED.get(name)
    if failed is not None and failed(result):
        return "error"
    warned = _STAGE_WARNED.get(name)
    if warned is not None and warned(result):
        return "warning"
    return "completed"


@dataclass
class PipelineResult:
    stages: list[StageRecord] = field(default_factory=list)
    has_errors: bool = False
    duration_seconds: float = 0.0
    started_at: datetime = field(
        default_factory=lambda: datetime.now(UTC))
    log_start: int | None = None
    log_end: int | None = None


class _StopRequested(Exception):
    pass


def setup_logging():
    log_file = config.LOG_FILE
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(handler, logging.FileHandler)
           and handler.baseFilename == os.path.abspath(log_file)
           for handler in root.handlers):
        return

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)


def check_dependencies():
    if not config.FFMPEG.is_file():
        raise RuntimeError(f"Topaz ffmpeg not found: {config.FFMPEG}")
    probe = subprocess.run(["ffprobe", "-version"], capture_output=True, check=False,
                           **hidden_subprocess_kwargs())
    if probe.returncode != 0:
        raise RuntimeError("ffprobe not found in PATH")


def throttle_nonai_to_presence() -> str:
    return nonai_upscale.throttle_to_presence()


def upscale_queue() -> upscale_queue_shape.UpscaleQueue:
    return nonai_upscale_queue.current()


def arrange_upscale_queue(videos: list[str]) -> None:
    nonai_queue.pin_ahead(config.NONAI_PIN_LIST, videos)


def upscale_now(video: str) -> None:
    nonai_request.request_now(video)


def upscale_next(video: str) -> None:
    nonai_request.put_first(video)


def withdraw_upscale_now() -> None:
    nonai_request.withdraw_request()


def run_pipeline(
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
    nonai_enabled: bool | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> PipelineResult:
    with run_lock.held(config.PIPELINE_LOCK_FILE):
        return _run_stages(on_stage_start, on_stage_complete, on_stage_progress,
                           nonai_enabled, should_stop)


def _run_stages(
    on_stage_start: Callable[[str], None] | None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None,
    on_stage_progress: Callable[[str, int, int], None] | None,
    nonai_enabled: bool | None,
    should_stop: Callable[[], bool] | None,
) -> PipelineResult:
    log = logging.getLogger(__name__)
    pipeline_t0 = time.monotonic()
    started_at = datetime.now(UTC)
    log_path = config.LOG_FILE
    run_id = run_log.run_id(started_at)
    log_start = run_log.size(log_path)
    log.info(run_log.banner(run_id))
    records: list[StageRecord] = []

    def _run_stage(name, fn, **kwargs):
        if should_stop is not None and should_stop():
            raise _StopRequested
        if on_stage_start:
            on_stage_start(name)
        t0 = time.monotonic()
        result = fn(**kwargs)
        elapsed = time.monotonic() - t0
        status = _stage_status(name, result)
        records.append(StageRecord(name, status, elapsed, result))
        if on_stage_complete:
            on_stage_complete(name, result, elapsed, status)
        log.info("")
        return result

    def _skip_stage(name, reason):
        if should_stop is not None and should_stop():
            raise _StopRequested
        if on_stage_start:
            on_stage_start(name)
        records.append(StageRecord(name, "skipped", 0.0, skip_reason=reason))
        if on_stage_complete:
            on_stage_complete(name, None, 0.0, "skipped")

    try:
        _run_stage("strays", stray_files.run)
        _run_stage("withdrawn", taken_back.run)
        _run_stage("metadata", prompt_scrape.run)
        sort_result = _run_stage("sort", sort.run)
        downtime_result = _run_stage("origenerator_downtime", origenerator_downtime.run)

        priority_files = getattr(sort_result, "moved_files", [])
        upscale_result = None
        upscale_skipped = False
        if not upscale.has_pending_work(priority_files=priority_files):
            log.info("No pending upscale work found. Skipping upscale.")
            _skip_stage("upscale", "no_pending_work")
        elif downtime_result is not None and downtime_result.holds_the_graphics_card:
            log.info("Skipping upscale: Origenerator is training a fix on the graphics card.")
            upscale_skipped = True
            _skip_stage("upscale", "origenerator_training")
        elif nonai_upscale.foreign_topaz_running():
            log.info("Skipping upscale: a Topaz encode Evolver did not start is running.")
            upscale_skipped = True
            _skip_stage("upscale", "topaz_busy")
        else:
            with nonai_upscale.frozen_for_ai_videos():
                if _should_skip_upscale_due_to_cpu(log):
                    log.info("Skipping upscale because CPU usage is above the configured threshold.")
                    upscale_skipped = True
                    _skip_stage("upscale", "cpu_busy")
                elif topaz.sign_in_expired():
                    log.info("Skipping upscale: Topaz's sign-in has expired, and Topaz can watermark "
                             "what it makes until someone signs in to the Topaz Video app.")
                    upscale_skipped = True
                    _skip_stage("upscale", topaz.SIGN_IN_EXPIRED)
                else:
                    upscale_kwargs: dict = dict(
                        priority_files=priority_files, max_items=config.UPSCALE_BATCH_LIMIT,
                    )
                    if on_stage_progress is not None:
                        upscale_kwargs["on_progress"] = lambda cur, tot: on_stage_progress("upscale", cur, tot)
                    upscale_result = _run_stage("upscale", upscale.run, **upscale_kwargs)

        _run_stage("genau_deliver", genau_deliver.run)

        upscale_still_pending = (
            upscale_skipped
            or (upscale_result is not None and upscale_result.pending_after_run > 0)
        )

        ai_drained = not upscale_skipped and (
            upscale_result is None or upscale_result.pending_after_run == 0
        )
        nonai_allow_start = bool(
            nonai_enabled and ai_drained and not _should_skip_upscale_due_to_cpu(log)
        )
        _run_stage(
            "upscale_non_ai", nonai_upscale.run,
            allow_start=nonai_allow_start, stop=nonai_enabled is False,
            presence_managed=nonai_enabled is True,
            take_requests=nonai_enabled is not None,
            ai_waiting=not ai_drained,
        )

        if upscale_still_pending:
            log.info("Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
            _skip_stage("verify", "upscale_pending")
        else:
            _run_stage("verify", check_correspondence.run, show_popup=True)

        _run_stage("references", reference_sync.run)
        _run_stage("watch_weights", watch_weights.run)
        _run_stage("bookmarks", bookmarks_sync.run)
        _run_stage("clip_scripts", clip_scripts.run)
        _run_stage("scene_scripts", scene_scripts.run)
        _run_stage("scripts", scripts_sync.run, show_popup=True)
        _run_stage("group_non_ai", nonai_group.run)
        _run_stage("title_non_ai", nonai_titles.run)
        _run_stage("video_types", video_kinds.run)
        _run_stage("provenance", provenance_sweep.run)
        _run_stage("dupes", check_duplicate_sizes.run, show_popup=True)
    except _StopRequested:
        log.warning(
            "Stop requested; dropping the remaining stages after %d ran.", len(records),
        )

    duration_seconds = time.monotonic() - pipeline_t0
    log_end = run_log.size(log_path)
    return PipelineResult(
        stages=records,
        has_errors=any(record.status == "error" for record in records),
        duration_seconds=duration_seconds,
        started_at=started_at,
        log_start=log_start,
        log_end=log_end,
    )


def main():
    setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_dependencies()
    except RuntimeError as e:
        log.exception("Dependency check failed: %s", e)
        sys.exit(1)

    try:
        result = run_pipeline()
    except run_lock.Busy as busy:
        log.warning("Did not run: %s.", busy)
        sys.exit(1)
    sys.exit(1 if result.has_errors else 0)


def _should_skip_upscale_due_to_cpu(log: logging.Logger) -> bool:
    try:
        busy_percent = system_resources.measure_cpu_busy_percent(
            config.CPU_BUSY_SKIP_SAMPLE_SECONDS)
    except Exception:
        log.exception("CPU usage probe failed; proceeding with the upscale stage.")
        return False

    log.info(
        "CPU busy sample: %.1f%% (threshold %.1f%%)",
        busy_percent,
        config.CPU_BUSY_SKIP_THRESHOLD_PCT,
    )
    return busy_percent >= config.CPU_BUSY_SKIP_THRESHOLD_PCT


if __name__ == "__main__":
    main()
