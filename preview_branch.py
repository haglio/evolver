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

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs
from PyQt6.QtWidgets import QApplication

import config
from evolver import PipelineResult, StageRecord
from gui.main_window import EvolverMainWindow
from gui.queue_window import UpscaleQueueWindow
from gui.run_record import RunRecord, save_run
from gui.sign_in_notice import SignInNotice
from tasks import nonai_lineup, nonai_progress, nonai_queue, nonai_titles, nonai_upscale, withdrawn
from tasks.nonai_queue import collect_candidates, relpath
from tasks.nonai_upscale import NonAiUpscaleResult, StageFiles
from util import crash_log, nonai_job, processes, sidecar, topaz, video_type
from util.ffprobe import duration_seconds
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets
from util.variants import is_processed_stem

PROJECT_ROOT = Path(__file__).resolve().parent

log = logging.getLogger(__name__)


def sign_in_deferral() -> str:
    if processes.count_running(config.FFMPEG) or not topaz.sign_in_expired():
        return ""
    return topaz.SIGN_IN_EXPIRED


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
        if is_finalized_video_file(video)
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
            sidecar.update(path, lambda _, seconds=seconds: video_type.timed({}, seconds))


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
        start_deferred=sign_in_deferral(),
    )
    return StageRecord(name="upscale_non_ai", status="completed",
                       duration_seconds=time.monotonic() - started, result=result)


def withdrawn_report(preview_metadata: Path, primary: Path) -> StageRecord:
    """What the live run would delete for clips Origenerator has taken back.

    Counted, never deleted: this preview reads the real library, and a stage
    whose whole job is removing files cannot be shown by letting it do that.
    So the row says how many copies the next real run will take, which is the
    number worth judging before the stage lands at all. It takes the preview's
    two paths because every report does and reads neither, what it counts being
    in the library itself.
    """
    started = time.monotonic()
    copies = withdrawn.pending()
    result = withdrawn.WithdrawnResult(deleted=len(copies))
    return StageRecord(name="withdrawn", status="completed",
                       duration_seconds=time.monotonic() - started, result=result)


def _library_payloads() -> dict:
    """Every non-AI video's recorded document, keyed by its path."""
    return {
        video: sidecar.read(sidecar.sidecar_path(video))
        for bucket in buckets()
        for video in sorted(bucket.rglob("*"))
        if is_finalized_video_file(video)
    }


def nonai_titles_report(preview_metadata: Path, primary: Path) -> StageRecord:
    """How much of the library the clip records can name, without naming it.

    Read off the same documents the stage reads and written back to none of
    them: this preview reads the real library, and what is worth judging here is
    the count -- how far the clip records reach once a scene inherits from the
    clip cut out of it.  The two paths every report takes are unused for the
    same reason ``withdrawn_report``'s are.
    """
    started = time.monotonic()
    payloads = _library_payloads()
    titles = nonai_titles.titles_by_family(payloads)
    named = sum(
        1 for payload in payloads.values()
        if nonai_titles.clip_title(payload) or titles.get(nonai_titles.family_of(payload), "")
    )
    result = nonai_titles.NonAiTitleResult(titled=named, videos=len(payloads))
    return StageRecord(name="title_non_ai", status="completed",
                       duration_seconds=time.monotonic() - started, result=result)


#: The stages this preview can report on, in pipeline order.  Add one when a
#: change makes a stage's report worth judging; drop it when it stops being.
REPORTS = (withdrawn_report, nonai_upscale_report, nonai_titles_report)


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
                              check=False, **hidden_subprocess_kwargs())
    except OSError:
        return "this worktree"
    return done.stdout.strip() or "this worktree"


def preview_files(state: Path) -> StageFiles:
    """The records the queue window reads here, and where its writes land.

    Every one of them is the preview's own copy, under *state*, because every
    one of them is written by the window: rearranging the queue rewrites the
    pin manifest, and asking for a video writes the request and clears the job
    record.  Copied in at each launch (:func:`copy_the_live_records_in`) so
    what the window shows is the live queue and the live encode, while the
    live app's own copies are never the ones written.  Fun Time's watch stats
    are the exception: the queue is ordered by them and nothing here writes
    them.

    The names are the live resolution's rather than spelled again here.
    """
    live = StageFiles.configured()
    return StageFiles(
        job=state / live.job.name,
        attempts=state / live.attempts.name,
        cooldown=state / live.cooldown.name,
        skip_manifest=state / live.skip_manifest.name,
        pin_manifest=state / live.pin_manifest.name,
        watch_stats=live.watch_stats,
        request=state / live.request.name,
    )


def copy_the_live_records_in(primary: Path, files: StageFiles) -> None:
    """Fill the preview's copies from the live app's, where it has one.

    The two manifests are read from the *primary* checkout rather than from
    this worktree: they are the user's, and a preview reading the branch's own
    empty copies would show a queue nobody has ever ordered.
    """
    live = StageFiles.configured()
    files.job.parent.mkdir(parents=True, exist_ok=True)
    for source, copy in (
        (primary / live.pin_manifest.name, files.pin_manifest),
        (primary / live.skip_manifest.name, files.skip_manifest),
        (live.job, files.job),
        (live.request, files.request),
    ):
        copy.unlink(missing_ok=True)
        if source.is_file():
            shutil.copyfile(source, copy)


def stopped_on_paper(job: dict, reason: str, files: StageFiles) -> str:
    """What stopping the encode in flight would come to, without stopping it.

    The live app kills the ffmpeg and deletes what it has written.  This
    preview is looking at that very encode, so it does neither: it clears its
    own copy of the record, which is what the window then draws.
    """
    log.info("Preview: would stop the encode of %s (%s).", job.get("source"), reason)
    nonai_job.clear_job(files.job)
    return relpath(Path(job.get("source", "")))


def taken_over_on_paper(job: dict, files: StageFiles) -> None:
    """The same for the encode that is already the one asked for: the live app
    thaws it, and this marks its copy of the record and thaws nothing."""
    job["on_request"] = True
    nonai_job.save_job(files.job, job)


# The live window hides to its tray icon when closed. A preview has no tray, so
# a hidden preview kept running unseen, holding its log open, and the next
# launch of the preview could not start.
class PreviewWindow(EvolverMainWindow):
    """The real window, on the preview's own records rather than the app's."""

    def __init__(self, files: StageFiles, parent=None):
        super().__init__(parent)
        self._files = files
        self._queue: UpscaleQueueWindow | None = None
        self.queue_action.triggered.connect(self.show_queue)

    def show_queue(self) -> None:
        """Open the upscale queue on what this branch makes of the real one."""
        if self._queue is None:
            self._queue = UpscaleQueueWindow(self)
            self._queue.arranged.connect(self._arrange)
            self._queue.now_requested.connect(self._ask_for)
            self._queue.refresh_wanted.connect(self._redraw)
        self._redraw()
        self._queue.show()
        self._queue.raise_()

    def _arrange(self, videos: list) -> None:
        nonai_queue.pin_ahead(self._files.pin_manifest, videos)
        self._redraw()

    def _ask_for(self, video: str) -> None:
        nonai_upscale.request_now(video, files=self._files, stop=stopped_on_paper,
                                  take_over=taken_over_on_paper)
        self._redraw()

    def _redraw(self) -> None:
        if self._queue is not None:
            self._queue.show_lineup(nonai_lineup.current(self._files))

    def closeEvent(self, event):
        event.accept()


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
    record = preview_record(PROJECT_ROOT / "state" / "preview-metadata", primary_checkout())
    save_run(record, config.RUNS_DIR)

    app = QApplication(sys.argv)
    SignInNotice().after_run(record, time.monotonic())
    files = preview_files(PROJECT_ROOT / "state")
    copy_the_live_records_in(primary_checkout(), files)
    window = PreviewWindow(files)
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
