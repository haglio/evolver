from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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
    origenerator_commands,
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
from util.stage_result import StageResult


@dataclass
class StageRecord:
    name: str
    status: str
    duration_seconds: float
    result: object | None = None
    skip_reason: str | None = None


def _status_of(result: StageResult) -> str:
    if not result.ok:
        return "error"
    return "warning" if result.needs_an_eye else "completed"


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


@dataclass
class _Stages:
    on_start: Callable[[str], None] | None
    on_complete: Callable[[str, object | None, float, str], None] | None
    should_stop: Callable[[], bool] | None
    records: list[StageRecord] = field(default_factory=list)


def _begin_stage(stages: _Stages, name: str):
    if stages.should_stop is not None and stages.should_stop():
        raise _StopRequested
    if stages.on_start:
        stages.on_start(name)


def _run_stage(stages: _Stages, name, fn, **kwargs):
    _begin_stage(stages, name)
    t0 = time.monotonic()
    result = fn(**kwargs)
    elapsed = time.monotonic() - t0
    status = _status_of(result)
    stages.records.append(StageRecord(name, status, elapsed, result))
    if stages.on_complete:
        stages.on_complete(name, result, elapsed, status)
    logging.getLogger(__name__).info("")
    return result


def _skip_stage(stages: _Stages, name, reason):
    _begin_stage(stages, name)
    stages.records.append(StageRecord(name, "skipped", 0.0, skip_reason=reason))
    if stages.on_complete:
        stages.on_complete(name, None, 0.0, "skipped")


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
    stages = _Stages(on_stage_start, on_stage_complete, should_stop)

    try:
        _run_every_stage(stages, log, on_stage_progress, nonai_enabled)
    except _StopRequested:
        log.warning(
            "Stop requested; dropping the remaining stages after %d ran.", len(stages.records),
        )

    duration_seconds = time.monotonic() - pipeline_t0
    log_end = run_log.size(log_path)
    return PipelineResult(
        stages=stages.records,
        has_errors=any(record.status == "error" for record in stages.records),
        duration_seconds=duration_seconds,
        started_at=started_at,
        log_start=log_start,
        log_end=log_end,
    )


def _run_every_stage(stages: _Stages, log: logging.Logger,
                     on_stage_progress: Callable[[str, int, int], None] | None,
                     nonai_enabled: bool | None):
    sort_result, downtime_result = _run_intake_stages(stages)
    priority_files = getattr(sort_result, "moved_files", [])
    upscale_result, upscale_skipped = _upscale_stage(
        stages, log, priority_files, downtime_result, on_stage_progress)
    _run_remaining_stages(stages, log, upscale_result, upscale_skipped, nonai_enabled)


def _run_intake_stages(stages: _Stages):
    _run_stage(stages, "strays", stray_files.run)
    _run_stage(stages, "withdrawn", taken_back.run)
    _run_stage(stages, "metadata", prompt_scrape.run)
    sort_result = _run_stage(stages, "sort", sort.run)
    downtime_result = _run_stage(stages, "origenerator_downtime",
                                 origenerator_commands.run_downtime)
    return sort_result, downtime_result


def _upscale_stage(stages: _Stages, log: logging.Logger, priority_files,
                   downtime_result, on_stage_progress):
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending upscale work found. Skipping upscale.")
        _skip_stage(stages, "upscale", "no_pending_work")
        return None, False
    if downtime_result is not None and downtime_result.holds_the_graphics_card:
        log.info("Skipping upscale: Origenerator is training a fix on the graphics card.")
        _skip_stage(stages, "upscale", "origenerator_training")
        return None, True
    if nonai_upscale.foreign_topaz_running():
        log.info("Skipping upscale: a Topaz encode Evolver did not start is running.")
        _skip_stage(stages, "upscale", "topaz_busy")
        return None, True
    with nonai_upscale.frozen_for_ai_videos():
        return _upscale_unless_the_computer_is_unfit(
            stages, log, priority_files, on_stage_progress)


def _upscale_unless_the_computer_is_unfit(stages: _Stages, log: logging.Logger,
                                          priority_files, on_stage_progress):
    if _should_skip_upscale_due_to_cpu(log):
        log.info("Skipping upscale because CPU usage is above the configured threshold.")
        _skip_stage(stages, "upscale", "cpu_busy")
        return None, True
    if topaz.sign_in_expired():
        log.info("Skipping upscale: Topaz's sign-in has expired, and Topaz can watermark "
                 "what it makes until someone signs in to the Topaz Video app.")
        _skip_stage(stages, "upscale", topaz.SIGN_IN_EXPIRED)
        return None, True
    listeners = upscale.Listeners(
        on_filed=origenerator_commands.write_the_gallery_entry_of_a_video_from)
    if on_stage_progress is not None:
        listeners = replace(
            listeners, on_progress=lambda cur, tot: on_stage_progress("upscale", cur, tot))
    return _run_stage(stages, "upscale", upscale.run, priority_files=priority_files,
                      max_items=config.UPSCALE_BATCH_LIMIT, listeners=listeners), False


def _run_remaining_stages(stages: _Stages, log: logging.Logger, upscale_result,
                          upscale_skipped: bool, nonai_enabled: bool | None):
    _run_stage(stages, "genau_deliver", genau_deliver.run)

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
        stages, "upscale_non_ai", nonai_upscale.run,
        mode=nonai_upscale.RunMode(
            allow_start=nonai_allow_start, stop=nonai_enabled is False,
            presence_managed=nonai_enabled is True,
            take_requests=nonai_enabled is not None,
            ai_waiting=not ai_drained),
    )

    if upscale_still_pending:
        log.info("Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
        _skip_stage(stages, "verify", "upscale_pending")
    else:
        _run_stage(stages, "verify", check_correspondence.run, show_popup=True)

    _run_stage(stages, "references", reference_sync.run)
    _run_stage(stages, "watch_weights", watch_weights.run,
               tell_the_gallery=origenerator_commands.write_gallery_entries)
    _run_stage(stages, "bookmarks", bookmarks_sync.run)
    _run_stage(stages, "clip_scripts", clip_scripts.run)
    _run_stage(stages, "scene_scripts", scene_scripts.run)
    _run_stage(stages, "scripts", scripts_sync.run, show_popup=True)
    _run_stage(stages, "group_non_ai", nonai_group.run)
    _run_stage(stages, "title_non_ai", nonai_titles.run)
    _run_stage(stages, "video_types", video_kinds.run)
    _run_stage(stages, "provenance", provenance_sweep.run)
    _run_stage(stages, "dupes", check_duplicate_sizes.run, show_popup=True)


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
