#!/usr/bin/env pythonw
"""Open THIS WORKTREE's Evolver window on what the branch says about the real
library, so a user-facing change can be judged before it lands.

Evolver cannot be previewed the way its siblings are.  Origenerator's preview
runs a second app instance against a state folder of its own; Evolver's whole
job is moving files in the one library, and its non-AI stage supervises a
detached multi-hour encode through a pid in a file — a second pipeline would
move the same files and adopt the same encode.  So this never runs the
pipeline and never starts the tray.  It reads the library, builds the run
record those reads would have produced, and opens the real window on it: the
same run-detail table the live app draws, out of the same code.  The live app
can stay running; nothing here contends with it.

Nothing it writes is anywhere the live app looks.  The run record goes in this
worktree's own ``runs/``, and the running times it measures go in a preview
metadata tree beside it — never in the library's, which ``tasks.video_types``
owns.

Which stages get a row is per-change, and this is where that lives: one
function per stage whose report is worth judging, each returning the
``StageRecord`` the pipeline would have made, filled from reads alone.  A stage
whose report cannot be reached without doing the work gets no row rather than
an invented one, and on the ones that do get a row the event fields — what
started, what finished — stay empty, there having been no tick.

Started by double-clicking ``launch_preview_branch.vbs`` beside this file,
never by hand: it borrows the primary checkout's venv and re-copies the
primary's content overlay, without which this comes up on the committed example
overlay and finds no library at all.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication

import config
from evolver import PipelineResult, StageRecord
from gui.main_window import EvolverMainWindow
from gui.run_record import RunRecord, save_run
from tasks import nonai_progress
from tasks.nonai_queue import collect_candidates
from tasks.nonai_upscale import NonAiUpscaleResult
from util import crash_log, sidecar, video_type
from util.ffprobe import duration_seconds
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets
from util.variants import is_processed_stem

PROJECT_ROOT = Path(__file__).resolve().parent


def primary_checkout(project_root: Path = PROJECT_ROOT) -> Path:
    """The checkout the user actually runs, which is where their own files are.

    A worktree sits at ``<primary>/.claude/worktrees/<name>``, so the primary is
    three levels up from one, and is here when this is run from the primary
    itself.  The skip and pin manifests are the user's, hand-edited, and
    ``config`` keeps them inside the checkout — so a preview reading the
    branch's own empty copies would show a queue nobody has ever ordered.
    """
    parents = project_root.parents
    if (len(parents) >= 3
            and parents[0].name == "worktrees" and parents[1].name == ".claude"):
        return parents[2]
    return project_root


def _upscales() -> list[Path]:
    """Every processed variant in the buckets — the done half of the project."""
    return [
        video
        for bucket in buckets()
        for video in sorted(bucket.rglob("*"))
        if is_finalized_video_file(video, config.VIDEO_EXTENSIONS)
        and is_processed_stem(video.stem)
    ]


def _seed_running_times(preview_metadata: Path, videos: list[Path]) -> None:
    """Give the preview's metadata tree a running time for every project video.

    Taken off the library's own sidecar where ``tasks.video_types`` has already
    recorded one, and measured here where it has not — so the preview shows the
    picture the library settles at rather than however far that backfill has
    got, which on a library it has never been over is nowhere.  An ffprobe
    apiece costs a couple of minutes the first time and nothing after: the
    answers stay in the preview tree, and the live app's own records take over
    as they arrive.

    Redirecting ``METADATA_DIR`` is what keeps this out of the library: every
    read above happens against the real tree first, and only then does the
    module-level path move, so what is written lands in the preview's copy.
    """
    from_library = {
        video: video_type.duration_of(sidecar.read(sidecar.sidecar_path(video)))
        for video in videos
    }
    config.METADATA_DIR = preview_metadata
    for video, seconds in from_library.items():
        path = sidecar.sidecar_path(video)
        if seconds is None:
            seconds = video_type.duration_of(sidecar.read(path)) or duration_seconds(video)
        if seconds is not None:
            sidecar.write(path, video_type.timed({}, seconds))


def nonai_upscale_report(preview_metadata: Path, primary: Path) -> StageRecord:
    """What the non-AI upscale stage would say about the library right now.

    Its reporting half and none of the rest: the queue in the order the stage
    would take it, and how far through the project that queue leaves the
    library.  Nothing is started, supervised, promoted or retired, so the
    result's event fields stay empty and the row reads as the tick where
    nothing happened — which is most of them.
    """
    started = time.monotonic()
    queued = collect_candidates(
        skip_manifest=primary / config.NONAI_SKIP_MANIFEST.name,
        pin_manifest=primary / config.NONAI_PRIORITY_MANIFEST.name,
        watch_stats_file=config.FUN_TIME_WATCH_STATS_FILE,
    )
    _seed_running_times(preview_metadata, [c.path for c in queued] + _upscales())
    progress = nonai_progress.so_far(candidate.path for candidate in queued)
    result = NonAiUpscaleResult(
        pending=len(queued),
        percent_complete=progress.percent,
        remaining_seconds=progress.remaining_seconds,
        unmeasured_videos=progress.unmeasured,
    )
    return StageRecord(name="upscale_non_ai", status="completed",
                       duration_seconds=time.monotonic() - started, result=result)


#: The stages this preview can report on, in pipeline order.  Add one when a
#: change makes a stage's report worth judging; drop it when it stops being.
REPORTS = (nonai_upscale_report,)


def preview_record(preview_metadata: Path, primary: Path) -> RunRecord:
    """One run record holding every report, as the pipeline would have written."""
    stages = [report(preview_metadata, primary) for report in REPORTS]
    return RunRecord.from_pipeline_result(
        PipelineResult(stages=stages, has_errors=False,
                       duration_seconds=sum(s.duration_seconds for s in stages)),
        trigger="preview",
    )


def branch_name() -> str:
    """The branch this worktree is on, for the window's title."""
    try:
        done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=PROJECT_ROOT, capture_output=True, text=True,
                              check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        return "this worktree"
    return done.stdout.strip() or "this worktree"


def main() -> int:
    """Build the record, then show it in the real window.

    The window's commands are disabled rather than left connected to nothing:
    a Run Now that silently does nothing is worse than one that is plainly not
    on offer, and running anything is the thing this must never do.  The title
    says which branch, because a window that cannot be told from the live app's
    is how a review cycle gets spent on the wrong code.
    """
    crash_log.install_excepthook()
    config.RUNS_DIR = PROJECT_ROOT / "runs"
    save_run(preview_record(PROJECT_ROOT / "state" / "preview-metadata",
                            primary_checkout()), config.RUNS_DIR)

    app = QApplication(sys.argv)
    window = EvolverMainWindow()
    window.setWindowTitle(f"Evolver — preview of {branch_name()}")
    for action in (window.run_now_action, window.settings_action, window.stats_action,
                   window.restart_action, window.quit_action):
        action.setEnabled(False)
    window.active_toggle.setEnabled(False)
    window.refresh_history()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
