from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType

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
    video_labels,
    watch_weights,
)
from tasks.origenerator_commands import DowntimeResult
from tasks.sort import SortResult
from tasks.upscale import UpscaleResult
from util import run_lock, run_log, system_resources, topaz
from util import upscale_queue as upscale_queue_shape
from util.stage_result import StageResult

COMPLETED = "completed"
WARNING = "warning"
ERROR = "error"
SKIPPED = "skipped"

_FLICK = config.GENAU_FLICK_WORD
_NO_PENDING_WORK = "no_pending_work"


@dataclass(frozen=True)
class Skipped:
    reason: str


@dataclass
class ThisRun:
    nonai_enabled: bool | None = None
    on_progress: Callable[[str, int, int], None] | None = None
    outcomes: dict[str, StageResult | Skipped] = field(default_factory=dict)

    def outcome_of(self, key: str) -> StageResult | Skipped | None:
        return self.outcomes.get(key)

    def progress_of(self, key: str) -> Callable[[int, int], None] | None:
        on_progress = self.on_progress
        if on_progress is None:
            return None
        return lambda current, total: on_progress(key, current, total)


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    tooltip: str
    color: tuple[int, int, int]
    run: Callable[[ThisRun], StageResult | Skipped]


def _upscale(this_run: ThisRun) -> StageResult | Skipped:
    log = logging.getLogger(__name__)
    sorted_ = this_run.outcome_of("sort")
    priority_files = sorted_.moved_files if isinstance(sorted_, SortResult) else []
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending upscale work found. Skipping upscale.")
        return Skipped(_NO_PENDING_WORK)
    downtime = this_run.outcome_of("origenerator_downtime")
    if isinstance(downtime, DowntimeResult) and downtime.holds_the_graphics_card:
        log.info("Skipping upscale: Origenerator is training a fix on the graphics card.")
        return Skipped("origenerator_training")
    if nonai_upscale.foreign_topaz_running():
        log.info("Skipping upscale: a Topaz encode Evolver did not start is running.")
        return Skipped("topaz_busy")
    with nonai_upscale.frozen_for_ai_videos():
        return _upscale_unless_the_computer_is_unfit(this_run, priority_files)


def _upscale_unless_the_computer_is_unfit(this_run: ThisRun,
                                          priority_files) -> StageResult | Skipped:
    log = logging.getLogger(__name__)
    if _should_skip_upscale_due_to_cpu(log):
        log.info("Skipping upscale because CPU usage is above the configured threshold.")
        return Skipped("cpu_busy")
    if topaz.sign_in_expired():
        log.info("Skipping upscale: Topaz's sign-in has expired, and Topaz can watermark "
                 "what it makes until someone signs in to the Topaz Video app.")
        return Skipped(topaz.SIGN_IN_EXPIRED)
    listeners = upscale.Listeners(
        on_filed=origenerator_commands.write_the_gallery_entry_of_a_video_from)
    on_progress = this_run.progress_of("upscale")
    if on_progress is not None:
        listeners = replace(listeners, on_progress=on_progress)
    return upscale.run(priority_files=priority_files, max_items=config.UPSCALE_BATCH_LIMIT,
                       listeners=listeners)


def _ai_videos_still_waiting(this_run: ThisRun) -> bool:
    upscaled = this_run.outcome_of("upscale")
    if isinstance(upscaled, Skipped):
        return upscaled.reason != _NO_PENDING_WORK
    return isinstance(upscaled, UpscaleResult) and upscaled.pending_after_run > 0


def _upscale_non_ai(this_run: ThisRun) -> StageResult:
    nonai_enabled = this_run.nonai_enabled
    ai_waiting = _ai_videos_still_waiting(this_run)
    allow_start = bool(nonai_enabled and not ai_waiting
                       and not _should_skip_upscale_due_to_cpu(logging.getLogger(__name__)))
    return nonai_upscale.run(mode=nonai_upscale.RunMode(
        allow_start=allow_start, stop=nonai_enabled is False,
        presence_managed=nonai_enabled is True,
        take_requests=nonai_enabled is not None,
        ai_waiting=ai_waiting))


def _verify(this_run: ThisRun) -> StageResult | Skipped:
    if _ai_videos_still_waiting(this_run):
        logging.getLogger(__name__).info(
            "Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
        return Skipped("upscale_pending")
    return check_correspondence.run(show_popup=True)


STAGES: tuple[Stage, ...] = (
    Stage("strays", "Stray Files",
          "Repair a video whose extension separator is not a dot, send a funscript found in the video tree to its mirror path under the scripts -- marking one Origenerator handed over as a script no person wrote -- and report every other non-video file found there",
          (0x0A, 0x12, 0x2C), run=lambda _: stray_files.run()),
    Stage("withdrawn", "Taken Back",
          "Delete every copy this library holds of a video Origenerator has taken back -- the inbox copy, the 1_sorted copy, the upscale and, down the Genau lane, the delivered "
          f"{_FLICK} -- with their metadata and funscripts, read off that app's own gallery, which is the only place the withdrawal is recorded; and, in each lane, a video's copy without its sound once the video with its sound is there",
          (0x00, 0x00, 0x6C), run=lambda _: taken_back.run()),
    Stage("metadata", "Metadata Scrape",
          "Scrape AI prompt metadata into mirrored JSON files",
          (0x14, 0x7D, 0x3C), run=lambda _: prompt_scrape.run()),
    Stage("labels", "Actions",
          "Copy onto each AI video's sidecar the actions Origenerator labels it with -- its image's, "
          "then its own, then the boxes checked on it -- which Fun Time filters and groups by",
          (0xEE, 0x22, 0x00), run=lambda _: video_labels.run()),
    Stage("sort", "Sort Inbox",
          "Move AI videos from 0_inbox into 1_sorted by source and orientation",
          (0x38, 0x6A, 0x9C), run=lambda _: sort.run()),
    Stage("origenerator_downtime", "Origenerator Downtime",
          "While Origenerator is closed, start the work it leaves for then: training a fix whose "
          "photos have changed, and the experiments and other runs it used to hand ComfyUI as it "
          "closed. The upscale waits while a fix trains, since the training needs the graphics card",
          (0x30, 0xD0, 0x40), run=lambda _: origenerator_commands.run_downtime()),
    Stage("upscale", "Upscale",
          "Apply Topaz 60fps frame interpolation + 4x upscale + various AI enhancements to 1_sorted AI videos, placing them in 2_outbox",
          (0xED, 0xC9, 0x48), run=_upscale),
    Stage("genau_deliver", "Genau Delivery",
          f"Move each upscaled Genau-lane {_FLICK} out of 2_outbox into the folder Genau plays from, retiring the 1_sorted copy it was made from — both halves leave together or the upscale stage redoes the {_FLICK} forever",
          (0x7B, 0x41, 0x73), run=lambda _: genau_deliver.run()),
    Stage("upscale_non_ai", "Upscale non-AI",
          "Supervise one detached Topaz encode of a 2D/non_AI video (apo-8 60fps + iris-2 toward 4K); with the toggle on, run it while the user is idle and the AI queue is drained, suspending it the moment they return",
          (0x76, 0x67, 0x47), run=_upscale_non_ai),
    Stage("verify", "Correspondence Check",
          "Verify 1_sorted and 2_outbox are in 1-to-1 correspondence",
          (0xFF, 0x9D, 0x83), run=_verify),
    Stage("references", "Follow Moved Videos",
          "Repoint the suite's saved video paths — Genaumacher sessions, Scripture projects and Fun Time's watch counts — at videos that have since moved",
          (0x61, 0xCA, 0xF2), run=lambda _: reference_sync.run()),
    Stage("watch_weights", "Watch Weights",
          "Sum Fun Time's and Warm Gun's completions, skips and locks on every library video's sidecar as the playback weight both apps shuffle by, and mark the phone's favorites on their sidecars",
          (0xB5, 0xE6, 0x1D),
          run=lambda _: watch_weights.run(
              tell_the_gallery=origenerator_commands.write_gallery_entries)),
    Stage("bookmarks", "Bookmarks Sync",
          "Sync Fun Time favorites into a Chrome bookmarks folder",
          (0x4B, 0x96, 0x88), run=lambda _: bookmarks_sync.run()),
    Stage("clip_scripts", "Clip Scripts",
          "Cut each carved clip's funscript out of its source scene's, using the offset the clip was matched at",
          (0xF6, 0x70, 0x99), run=lambda _: clip_scripts.run()),
    Stage("scene_scripts", "Scene Scripts",
          "Give an unscripted source scene a mostly-blank funscript holding its carved clip's, placed where the clip sits in it",
          (0xDE, 0xB8, 0xC6), run=lambda _: scene_scripts.run()),
    Stage("scripts", "Scripts Sync",
          "Align funscripts to mirror the video library tree",
          (0xAD, 0x40, 0x35), run=lambda _: scripts_sync.run(show_popup=True)),
    Stage("group_non_ai", "Group non-AI",
          "Record each 2D/non_AI video's version family (the original and its processed versions, and copies that look the same) in a mirrored metadata sidecar",
          (0x6F, 0xDB, 0x9A), run=lambda _: nonai_group.run()),
    Stage("title_non_ai", "Title non-AI",
          "Record what to call each 2D/non_AI video -- the performer and movie its clip record names, carried to the whole scene that clip was cut out of -- so every app reads one name instead of working it out at launch",
          (0xAA, 0x44, 0xCC), run=lambda _: nonai_titles.run()),
    Stage("video_types", "Video Kinds",
          f"Record what kind each library video is -- a generation, a clip, a Genau {_FLICK} -- and how long it runs, on its mirrored sidecar",
          (0x2B, 0x2B, 0xE8), run=lambda _: video_kinds.run()),
    Stage("provenance", "Provenance",
          "Record on each library video's sidecar what made it -- which app, which version of its code, which workflow or Topaz settings -- looking its videos up in Origenerator's gallery and reading the note Topaz wrote into each upscale, and marking unknown whatever neither can say",
          (0xEE, 0x00, 0xBB), run=lambda _: provenance_sweep.run()),
    Stage("dupes", "Duplicate Check",
          "Scan non_AI folder for likely duplicate videos, using exact filesize",
          (0xCA, 0x94, 0xDB), run=lambda _: check_duplicate_sizes.run(show_popup=True)),
)

ALL_STAGES = tuple(stage.key for stage in STAGES)
STAGE_LABELS = MappingProxyType({stage.key: stage.label for stage in STAGES})
STAGE_TOOLTIPS = MappingProxyType({stage.key: stage.tooltip for stage in STAGES})
STAGE_NUMBER = MappingProxyType({stage.key: number for number, stage in enumerate(STAGES, start=1)})


@dataclass
class StageRecord:
    name: str
    status: str
    duration_seconds: float
    result: object | None = None
    skip_reason: str | None = None


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


@dataclass(frozen=True)
class _Watchers:
    on_start: Callable[[str], None] | None
    on_complete: Callable[[str, object | None, float, str], None] | None
    should_stop: Callable[[], bool] | None


def run_pipeline(
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
    nonai_enabled: bool | None = None,
    should_stop: Callable[[], bool] | None = None,
    *,
    stages: Sequence[Stage] = STAGES,
) -> PipelineResult:
    this_run = ThisRun(nonai_enabled=nonai_enabled, on_progress=on_stage_progress)
    watchers = _Watchers(on_stage_start, on_stage_complete, should_stop)
    with run_lock.held(config.PIPELINE_LOCK_FILE):
        return _run_stages(stages, this_run, watchers)


def _run_stages(stages: Sequence[Stage], this_run: ThisRun, watchers: _Watchers) -> PipelineResult:
    log = logging.getLogger(__name__)
    pipeline_t0 = time.monotonic()
    started_at = datetime.now(UTC)
    log_path = config.LOG_FILE
    log_start = run_log.size(log_path)
    log.info(run_log.banner(run_log.run_id(started_at)))

    records: list[StageRecord] = []
    try:
        records.extend(_run_stage(stage, this_run, watchers) for stage in stages)
    except _StopRequested:
        log.warning("Stop requested; dropping the remaining stages after %d ran.", len(records))

    return PipelineResult(
        stages=records,
        has_errors=any(record.status == ERROR for record in records),
        duration_seconds=time.monotonic() - pipeline_t0,
        started_at=started_at,
        log_start=log_start,
        log_end=run_log.size(log_path),
    )


def _run_stage(stage: Stage, this_run: ThisRun, watchers: _Watchers) -> StageRecord:
    if watchers.should_stop is not None and watchers.should_stop():
        raise _StopRequested
    if watchers.on_start:
        watchers.on_start(stage.key)
    t0 = time.monotonic()
    outcome = stage.run(this_run)
    this_run.outcomes[stage.key] = outcome
    if isinstance(outcome, Skipped):
        if watchers.on_complete:
            watchers.on_complete(stage.key, None, 0.0, SKIPPED)
        return StageRecord(stage.key, SKIPPED, 0.0, skip_reason=outcome.reason)

    elapsed = time.monotonic() - t0
    status = _status_of(outcome)
    if watchers.on_complete:
        watchers.on_complete(stage.key, outcome, elapsed, status)
    logging.getLogger(__name__).info("")
    return StageRecord(stage.key, status, elapsed, outcome)


def _status_of(result: StageResult) -> str:
    if not result.ok:
        return ERROR
    return WARNING if result.needs_an_eye else COMPLETED


def main(*, stages: Sequence[Stage] = STAGES):
    setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_dependencies()
    except RuntimeError as e:
        log.exception("Dependency check failed: %s", e)
        sys.exit(1)

    try:
        result = run_pipeline(stages=stages)
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
