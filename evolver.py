#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Invoked by the tray app scheduler or directly via CLI.

What the stages are and what they are called is ``tasks/stages.py``, which is
also where their order is declared. ``run_pipeline`` below spells that order a
second time — it has to, because each stage carries its own arguments and skip
branches, and the reason for its position is a comment beside it — so the two
are held in step by ``tests/test_stage_registry.py`` rather than by one of them
being derived from the other. Two gates: one reads the names out of this file's
syntax tree, one runs the pipeline with its stages mocked.
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
    stray_files,
    upscale,
    video_types,
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
# together.
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

# What counts as worth a person's eye without being work gone wrong. Two shapes
# land here. Work held back: there is no room to write another upscale, so the
# stage parks the queue and picks it up again the moment space frees up. And a
# finding a person has to judge: the stray-files stage fixes what it can name and
# reports the rest, where reporting IS the stage doing its job rather than
# failing at it.
_STAGE_WARNED: dict[str, Callable[[object], bool]] = {
    "strays": lambda r: not r.ok,
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
    warned = _STAGE_WARNED.get(name)
    if warned is not None and warned(result):
        return "warning"
    return "completed"


@dataclass
class PipelineResult:
    """Aggregate result of all pipeline stages."""
    stages: list[StageRecord] = field(default_factory=list)
    has_errors: bool = False
    duration_seconds: float = 0.0


class _StopRequested(Exception):
    """Raised at a stage boundary once the caller's should_stop turns true."""


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
    # check=False, said out loud: the returncode is inspected below and turned
    # into the RuntimeError this function raises for every missing dependency,
    # rather than a CalledProcessError from one of them.
    probe = subprocess.run(["ffprobe", "-version"], capture_output=True, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    if probe.returncode != 0:
        raise RuntimeError("ffprobe not found in PATH")


def throttle_nonai_to_presence() -> str:
    """Suspend or resume the in-flight non-AI encode as the user comes and goes.

    The one thing the pipeline does while it is not running, and the GUI's one
    door to it. The layering here is ``util <- tasks <- evolver <- gui``: gui
    reaches the stages through this module and nothing else, so the window
    layer does not have to know which stage owns a detached ffmpeg.
    """
    return nonai_upscale.throttle_to_presence()


def run_pipeline(
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_complete: Callable[[str, object | None, float, str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
    nonai_enabled: bool | None = None,
    should_stop: Callable[[], bool] | None = None,
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
        should_stop: Checked at every stage boundary; once it returns True the
            remaining stages are dropped and the result covers what ran. Only
            between stages — a stage mid-move must finish its current file, so
            nothing interrupts one in flight.

    Returns:
        PipelineResult with per-stage records and aggregate status.
    """
    log = logging.getLogger(__name__)
    pipeline_t0 = time.monotonic()
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
        # First: every stage below finds videos by a positive extension filter and
        # funscripts only under the script tree, so a name this one repairs or a
        # script it rehomes is invisible to all of them until it has run.
        _run_stage("strays", stray_files.run)
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
        # After the grouping, which is what creates a new non-AI video's sidecar:
        # the kind then joins a record that is already there rather than making a
        # second one for the same video in the same run.
        _run_stage("video_types", video_types.run)
        _run_stage("dupes", check_duplicate_sizes.run, show_popup=True)
    except _StopRequested:
        log.warning(
            "Stop requested; dropping the remaining stages after %d ran.", len(records),
        )

    return PipelineResult(
        stages=records,
        has_errors=any(record.status == "error" for record in records),
        duration_seconds=time.monotonic() - pipeline_t0,
    )


def main():
    setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_dependencies()
    except RuntimeError as e:
        # exception, not error: the traceback names which dependency check
        # raised, which is the whole content of the diagnosis.
        log.exception("Dependency check failed: %s", e)
        sys.exit(1)

    result = run_pipeline()
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
