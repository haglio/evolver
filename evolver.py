#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Invoked by the tray app scheduler or directly via CLI. Stages:
  1. purge           - remove weird outputs and their matching sources
  2. metadata        - scrape AI prompt metadata into mirrored JSON files
  3. sort            - move new videos from inbox into sorted folders by source/orientation
  4. upscale         - apply Topaz frame interpolation + 4x upscale to sorted AI videos
  5. genau_deliver   - hand finished Genau clips to the folder Genau plays from
  6. upscale_non_ai  - supervise one detached Topaz encode of a non-AI library video
  7. verify          - check 1_sorted and 2_outbox are in 1-to-1 correspondence
  8. references      - repoint the suite's saved video paths at videos that moved
  9. bookmarks       - sync Fun Time favorites into a Chrome bookmarks folder
 10. clip_scripts    - cut a carved clip's funscript out of its source scene's
 11. scene_scripts   - place a carved clip's funscript back into its unscripted scene's
 12. scripts         - align funscripts to mirror the video library tree
 13. group_non_ai    - record each non-AI clip's version family in a mirrored sidecar
 14. dupes           - scan non_AI for likely duplicate videos by exact filesize
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
from tasks import (
    bookmarks_sync,
    clip_scripts,
    genau_deliver,
    nonai_group,
    nonai_upscale,
    prompt_scrape,
    purge_weird,
    reference_sync,
    scene_scripts,
    scripts_sync,
    sort,
    upscale,
)
from util import processes, system_resources


@dataclass
class StageRecord:
    """Result of a single pipeline stage."""
    name: str
    status: str  # "completed", "warning", "skipped", "error"
    duration_seconds: float
    result: object | None = None
    skip_reason: str | None = None


# What counts as a failure for each stage, read off that stage's own result. A
# stage absent here cannot fail. The run's verdict is then nothing more than its
# stages' verdicts (see ``run_pipeline``), which is what keeps the two legible
# together: a run used to read "error" while every stage it listed read
# "completed", because the verdict was computed from the result payloads and the
# stage status only ever recorded that the function had returned.
_STAGE_FAILED: dict[str, Callable[[object], bool]] = {
    "purge": lambda r: bool(r.missing_sorted),
    "metadata": lambda r: not r.ok,
    "upscale": lambda r: bool(r.failed),
    "upscale_non_ai": lambda r: bool(r.failed),
    # A clip that could not be delivered is almost always one Genau has open right
    # now, and the next run gets it — but it stays visible rather than silent,
    # because the alternative failure (a folder that cannot be written at all)
    # looks identical from here and would otherwise never be noticed.
    "genau_deliver": lambda r: bool(r.failed),
    "verify": lambda r: not r.ok,
    "references": lambda r: not r.ok,
    "bookmarks": lambda r: not r.ok,
    "scripts": lambda r: not r.ok,
    "dupes": lambda r: not r.ok,
}

# What counts as work held back rather than work gone wrong. Nothing broke and
# nothing is owed to anyone: there is no room to write another upscale, so the
# stage parks the queue and picks it up again the moment space frees up. This
# used to read as an outright failure, and because free space stays low for days
# at a stretch it turned the whole run history into a wall of red — a standing
# alarm for a condition with nothing in it to fix.
_STAGE_HELD_BACK: dict[str, Callable[[object], bool]] = {
    "upscale": lambda r: r.deferred_low_disk,
    "upscale_non_ai": lambda r: r.deferred_low_disk,
}


def _stage_status(name: str, result: object) -> str:
    """What *result* says about the stage, worst verdict first.

    A stage that both lost an encode and held the rest back reads "error": the
    dead encode wants a person, where the hold only wants disk space.
    """
    failed = _STAGE_FAILED.get(name)
    if failed is not None and failed(result):
        return "error"
    held_back = _STAGE_HELD_BACK.get(name)
    if held_back is not None and held_back(result):
        return "warning"
    return "completed"


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
    if subprocess.run(["ffprobe", "-version"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW).returncode != 0:
        raise RuntimeError("ffprobe not found in PATH")


def run_pipeline(
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
    nonai_enabled: bool | None = None,
) -> PipelineResult:
    """Run the full evolver pipeline, optionally reporting progress via callbacks.

    Args:
        on_stage_start: Called with (stage_name) before each stage runs.
        on_stage_complete: Called with (stage_name, result, elapsed_seconds, status)
            after each stage. status is "completed", "warning", "skipped", or
            "error".
        nonai_enabled: The tray's non-AI upscale toggle. True lets Evolver
            auto-manage an encode by user presence — starting or resuming it
            while the user is away, suspending it the moment they return. False
            stops an in-flight one, and None (headless CLI, which has no toggle)
            leaves any in-flight encode alone and starts nothing. Finished
            encodes are promoted in every mode.

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
        status = _stage_status(name, result)
        record = StageRecord(name, status, elapsed, result)
        stages.append(record)
        if on_stage_complete:
            on_stage_complete(name, result, elapsed, status)
        log.info("")
        return result

    def _skip_stage(name, reason):
        if on_stage_start:
            on_stage_start(name)
        record = StageRecord(name, "skipped", 0.0, skip_reason=reason)
        stages.append(record)
        if on_stage_complete:
            on_stage_complete(name, None, 0.0, "skipped")

    _run_stage("purge", purge_weird.run)
    _run_stage("metadata", prompt_scrape.run)
    sort_result = _run_stage("sort", sort.run)

    priority_files = getattr(sort_result, "moved_files", [])
    upscale_result = None
    upscale_skipped = False
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending upscale work found. Skipping upscale.")
        _skip_stage("upscale", "no_pending_work")
    elif processes.count_running(config.FFMPEG) > 0:
        # A detached non-AI encode (or a manual Topaz GUI export) already owns
        # the GPU; running the AI batch alongside it stacks Topaz processes,
        # which is what used to exhaust memory and crash the machine.
        log.info("Skipping upscale: a Topaz ffmpeg encode is already running.")
        upscale_skipped = True
        _skip_stage("upscale", "topaz_busy")
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

    # Straight after the upscale, so a clip made this run reaches Genau this run —
    # and before the correspondence check, which would otherwise see the delivered
    # clip's source still sitting in 1_sorted with nothing beside it in the outbox.
    _run_stage("genau_deliver", genau_deliver.run)

    upscale_still_pending = (
        upscale_skipped
        or (upscale_result is not None and upscale_result.pending_after_run > 0)
    )

    # The non-AI stage always runs (it may have a detached encode to check on),
    # but only starts a new multi-hour encode when the tray toggle is on, the
    # AI pipeline is drained, and the box is otherwise quiet.
    ai_drained = not upscale_skipped and (
        upscale_result is None or upscale_result.pending_after_run == 0
    )
    nonai_allow_start = bool(
        nonai_enabled and ai_drained and not _should_skip_upscale_due_to_cpu(log)
    )
    _run_stage(
        "upscale_non_ai", nonai_upscale.run,
        allow_start=nonai_allow_start, stop=nonai_enabled is False,
        # Toggle on -> Evolver manages the encode by user presence: suspend it
        # when someone's at the machine, resume it when they idle out.
        presence_managed=nonai_enabled is True,
    )

    if upscale_still_pending:
        log.info("Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
        _skip_stage("verify", "upscale_pending")
    else:
        _run_stage("verify", check_correspondence.run, show_popup=True)

    # After every stage that moves a video, and before bookmarks: both stages
    # touch favs.csv, and bookmarks drops the rows whose file is missing, so a
    # favorite has to be repointed before it can be mistaken for a dead one.
    _run_stage("references", reference_sync.run)
    _run_stage("bookmarks", bookmarks_sync.run)
    # Before the scripts sync: these write new funscripts into the tree, and the
    # sync is what settles them across a clip's version family. The two carry a
    # script between a clip and its scene in opposite directions, and each
    # leaves an existing script alone, so neither can undo the other.
    _run_stage("clip_scripts", clip_scripts.run)
    _run_stage("scene_scripts", scene_scripts.run)
    _run_stage("scripts", scripts_sync.run, show_popup=True)
    _run_stage("group_non_ai", nonai_group.run)
    _run_stage("dupes", check_duplicate_sizes.run, show_popup=True)

    return PipelineResult(
        stages=stages,
        has_errors=any(stage.status == "error" for stage in stages),
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
