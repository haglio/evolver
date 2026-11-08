from __future__ import annotations

import itertools
import logging
import os
import subprocess
import tempfile
import uuid
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import config
import evolver
from check_correspondence import CorrespondenceResult
from gui.run_record import RunRecord
from tasks import nonai_upscale
from tasks.genau_deliver import GenauDeliverResult
from tasks.nonai_upscale import NonAiUpscaleResult
from tasks.origenerator_commands import DowntimeResult
from tasks.sort import SortResult
from tasks.stray_files import StrayFilesResult
from tasks.taken_back import TakenBackResult
from tasks.upscale import UpscaleResult
from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir
from util import run_lock, run_log, topaz
from util.sidecar import sidecar_path
from util.stage_result import StageResult

WHAT_LOGGING_ENDS_A_LINE_WITH = os.linesep.encode("ascii")


@dataclass
class _Done(StageResult):
    went_wrong: bool = False
    wants_an_eye: bool = False

    @property
    def ok(self) -> bool:
        return not self.went_wrong

    @property
    def needs_an_eye(self) -> bool:
        return self.wants_an_eye


def _made_up(key: str, run=None) -> evolver.Stage:
    return evolver.Stage(key, f"Made-up {key}", f"A stage made up for a test: {key}",
                         (0x10, 0x20, 0x30), run=run or (lambda _: _Done()))


def _a_lock_the_running_evolver_does_not_hold():
    return override_config(PIPELINE_LOCK_FILE=Path(tempfile.gettempdir()) / "evolver-tests"
                           / f"pipeline-{uuid.uuid4().hex}.lock")


def _run(*stages: evolver.Stage, **listeners) -> evolver.PipelineResult:
    with _a_lock_the_running_evolver_does_not_hold():
        return evolver.run_pipeline(stages=stages, **listeners)


def _with_their_work_left_undone(stages=evolver.STAGES) -> tuple[evolver.Stage, ...]:
    return tuple(replace(stage, run=lambda _: _Done()) for stage in stages)


def _stage(key: str) -> evolver.Stage:
    return next(stage for stage in evolver.STAGES if stage.key == key)


def _statuses(result: evolver.PipelineResult) -> dict[str, str]:
    return {record.name: record.status for record in result.stages}


@contextmanager
def _writing_info_lines_like_the_banner_to(log: Path):
    handler = logging.FileHandler(log, encoding="utf-8")
    logger = logging.getLogger("evolver")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        with patch.object(config, "LOG_FILE", log):
            yield
    finally:
        logger.setLevel(previous_level)
        logger.removeHandler(handler)
        handler.close()


class TestTheListOfStagesRunsItself:
    def test_the_stages_run_in_the_order_the_list_gives_them(self):
        result = _run(_made_up("first"), _made_up("second"), _made_up("third"))

        assert [record.name for record in result.stages] == ["first", "second", "third"]

    def test_a_stage_added_to_the_list_runs_in_its_place_and_reaches_the_run_record(self):
        ran = []
        added = evolver.Stage("tidy_example", "Tidy Example", "Tidy the example folder",
                              (0x40, 0x50, 0x60), run=lambda _: ran.append("tidied") or _Done())

        record = RunRecord.from_pipeline_result(_run(_made_up("before"), added, _made_up("after")))

        assert ran == ["tidied"]
        assert [stage["name"] for stage in record.stages] == ["before", "tidy_example", "after"]
        assert record.stages[1]["status"] == "completed"
        assert record.stages[1]["result"] == {"went_wrong": False, "wants_an_eye": False}

    def test_the_pipeline_runs_every_stage_of_its_own_list_in_that_order(self):
        result = _run(*_with_their_work_left_undone())

        assert [record.name for record in result.stages] == list(evolver.ALL_STAGES)

    def test_each_stage_sees_how_the_stages_before_it_went(self):
        seen = []

        def look_back(this_run: evolver.ThisRun) -> _Done:
            seen.append((this_run.outcome_of("first"), this_run.outcome_of("second"),
                         this_run.outcome_of("third")))
            return _Done()

        _run(_made_up("first", run=lambda _: _Done(wants_an_eye=True)),
             _made_up("second", run=lambda _: evolver.Skipped("nothing to do")),
             _made_up("third", run=look_back))

        assert seen == [(_Done(wants_an_eye=True), evolver.Skipped("nothing to do"), None)]

    def test_each_stage_is_announced_as_it_starts(self):
        started = []

        _run(_made_up("first"), _made_up("second"), on_stage_start=started.append)

        assert started == ["first", "second"]

    def test_each_stage_reports_what_it_did_how_long_it_took_and_how_it_went(self):
        did = _Done(wants_an_eye=True)
        completed = Mock()

        _run(_made_up("first", run=lambda _: did), on_stage_complete=completed)

        key, result, seconds, status = completed.call_args.args
        assert (key, result, status) == ("first", did, "warning")
        assert isinstance(seconds, float)

    def test_a_stage_that_has_nothing_to_do_is_recorded_as_skipped_with_its_reason(self):
        completed = Mock()

        result = _run(_made_up("first", run=lambda _: evolver.Skipped("no_pending_work")),
                      on_stage_complete=completed)

        record = result.stages[0]
        assert (record.status, record.skip_reason, record.duration_seconds, record.result) == (
            "skipped", "no_pending_work", 0.0, None)
        completed.assert_called_once_with("first", None, 0.0, "skipped")

    def test_each_stage_reports_its_progress_under_its_own_name(self):
        progress = []

        _run(_made_up("counting", run=lambda this_run: this_run.progress_of("counting")(1, 5)
                      or _Done()),
             on_stage_progress=lambda *reported: progress.append(reported))

        assert progress == [("counting", 1, 5)]

    def test_a_run_without_a_progress_bar_hands_its_stages_none(self):
        handed = []

        _run(_made_up("counting", run=lambda this_run: handed.append(
            this_run.progress_of("counting")) or _Done()))

        assert handed == [None]

    def test_a_clean_run_reports_every_stage_it_ran_and_no_errors(self):
        result = _run(_made_up("first"), _made_up("second"))

        assert isinstance(result, evolver.PipelineResult)
        assert not result.has_errors
        assert _statuses(result) == {"first": "completed", "second": "completed"}

    def test_a_stage_that_went_wrong_is_the_one_marked_error_and_the_run_has_errors(self):
        result = _run(_made_up("first"), _made_up("second", run=lambda _: _Done(went_wrong=True)),
                      _made_up("third"))

        assert result.has_errors
        assert _statuses(result) == {"first": "completed", "second": "error", "third": "completed"}

    def test_a_stage_that_wants_an_eye_warns_instead_of_failing(self):
        result = _run(_made_up("first", run=lambda _: _Done(wants_an_eye=True)))

        assert _statuses(result) == {"first": "warning"}
        assert not result.has_errors

    def test_going_wrong_outranks_wanting_an_eye_on_the_same_stage(self):
        result = _run(_made_up("first", run=lambda _: _Done(went_wrong=True, wants_an_eye=True)))

        assert _statuses(result) == {"first": "error"}

    def test_an_undelivered_genau_video_fails_the_run(self):
        result = _run(replace(_stage("genau_deliver"), run=lambda _: GenauDeliverResult(failed=1)))

        assert _statuses(result) == {"genau_deliver": "error"}, (
            "a video Genau holds open is delivered next run, but a folder that cannot be written "
            "looks the same from here, and only a failure gets seen")

    def test_a_taken_back_video_left_undeleted_fails_the_run(self):
        result = _run(replace(_stage("withdrawn"), run=lambda _: TakenBackResult(failed=1)))

        assert _statuses(result) == {"withdrawn": "error"}, (
            "he was told the video was going; a silent failure would leave it in the library")

    def test_origenerator_not_answering_fails_the_run(self):
        result = _run(replace(_stage("origenerator_downtime"),
                              run=lambda _: DowntimeResult(failed=True)))

        assert _statuses(result) == {"origenerator_downtime": "error"}, (
            "the work Origenerator leaves for while it is closed would otherwise stop unseen")

    def test_a_stray_file_only_reported_warns(self):
        result = _run(replace(_stage("strays"),
                              run=lambda _: StrayFilesResult(reported=["notes.txt"])))

        assert _statuses(result) == {"strays": "warning"}, (
            "reporting what it cannot repair is the stage doing its job, not failing at it")
        assert not result.has_errors

    def test_upscales_held_back_for_disk_space_warn(self):
        result = _run(replace(_stage("upscale"),
                              run=lambda _: UpscaleResult(deferred_low_disk=True)))

        assert _statuses(result) == {"upscale": "warning"}, (
            "nothing broke: the queue resumes the moment room frees up")
        assert not result.has_errors

    def test_skips_alone_do_not_make_a_run_a_failure(self):
        result = _run(_made_up("first", run=lambda _: evolver.Skipped("cpu_busy")),
                      _made_up("second", run=lambda _: evolver.Skipped("upscale_pending")))

        assert _statuses(result) == {"first": "skipped", "second": "skipped"}
        assert not result.has_errors

    def test_duration_seconds_is_positive(self):
        a_clock_finer_than_any_mocked_run = itertools.count(start=1.0, step=1.0)
        with patch("evolver.time.monotonic", lambda: next(a_clock_finer_than_any_mocked_run)):
            result = _run(_made_up("first"))

        assert result.duration_seconds > 0.0

    def test_the_run_marks_its_own_stretch_of_the_log(self, tmp_path):
        log = tmp_path / "evolver.log"
        log.write_bytes(b"[2026-07-25 08:10:02] an earlier run" + WHAT_LOGGING_ENDS_A_LINE_WITH)
        with _writing_info_lines_like_the_banner_to(log):
            result = _run(_made_up("first"))

        text = run_log.read_run(log, run_log.run_id(result.started_at),
                                result.log_start, result.log_end)
        assert text is not None, (
            "what a run's stages said is only in this log, which is never rotated, so a run has "
            "to be found in it by its mark")
        assert "an earlier run" not in text

    def test_the_runs_stretch_ends_after_the_last_line_its_stages_logged(self, tmp_path):
        log = tmp_path / "evolver.log"

        def says_its_line(_):
            logging.getLogger("evolver.made_up").info("the last stage's line")
            return _Done()

        with _writing_info_lines_like_the_banner_to(log):
            result = _run(_made_up("first"), _made_up("last", run=says_its_line))

        text = run_log.read_run(log, run_log.run_id(result.started_at),
                                result.log_start, result.log_end)
        assert "the last stage's line" in text

    def test_a_log_it_cannot_measure_leaves_the_mark_unset(self):
        missing = Path("no-such-directory") / "evolver.log"
        with patch.object(config, "LOG_FILE", missing):
            result = _run(_made_up("first"))

        assert (result.log_start, result.log_end) == (None, None)


class TestCooperativeStop:
    def test_a_stop_asked_mid_stage_lets_that_stage_finish(self):
        asked = []

        result = _run(_made_up("first", run=lambda _: asked.append("stop") or _Done()),
                      _made_up("second"), _made_up("third"),
                      should_stop=lambda: bool(asked))

        assert _statuses(result) == {"first": "completed"}, (
            "a stage cut off mid-move would leave a video half moved")

    def test_a_stop_that_is_never_requested_changes_nothing(self):
        result = _run(_made_up("first"), _made_up("second"), should_stop=lambda: False)

        assert [record.name for record in result.stages] == ["first", "second"]


class TestEachStagesWork:
    @pytest.mark.parametrize(("key", "work", "settings"), [
        pytest.param("strays", "evolver.stray_files.run", {}, id="strays"),
        pytest.param("withdrawn", "evolver.unsent_videos.run", {}, id="withdrawn"),
        pytest.param("metadata", "evolver.prompt_scrape.run", {}, id="metadata"),
        pytest.param("labels", "evolver.video_labels.run", {}, id="labels"),
        pytest.param("sort", "evolver.sort.run", {}, id="sort"),
        pytest.param("origenerator_downtime", "evolver.origenerator_commands.run_downtime", {},
                     id="origenerator_downtime"),
        pytest.param("genau_deliver", "evolver.genau_deliver.run", {}, id="genau_deliver"),
        pytest.param("references", "evolver.reference_sync.run", {}, id="references"),
        pytest.param("watch_weights", "evolver.watch_weights.run",
                     {"tell_the_gallery": evolver.origenerator_commands.write_gallery_entries},
                     id="watch_weights tells origenerator's gallery"),
        pytest.param("bookmarks", "evolver.bookmarks_sync.run", {}, id="bookmarks"),
        pytest.param("clip_scripts", "evolver.clip_scripts.run", {}, id="clip_scripts"),
        pytest.param("scene_scripts", "evolver.scene_scripts.run", {}, id="scene_scripts"),
        pytest.param("scripts", "evolver.scripts_sync.run", {"show_popup": True},
                     id="scripts shows its popup"),
        pytest.param("group_non_ai", "evolver.nonai_group.run", {}, id="group_non_ai"),
        pytest.param("title_non_ai", "evolver.nonai_titles.run", {}, id="title_non_ai"),
        pytest.param("video_types", "evolver.video_kinds.run", {}, id="video_types"),
        pytest.param("provenance", "evolver.provenance_sweep.run", {}, id="provenance"),
        pytest.param("dupes", "evolver.check_duplicate_sizes.run", {"show_popup": True},
                     id="dupes shows its popup"),
    ])
    def test_each_stage_runs_its_own_work_and_hands_back_what_it_did(self, key, work, settings):
        did = _Done()
        with patch(work, return_value=did) as done:
            assert _stage(key).run(evolver.ThisRun()) is did

        done.assert_called_once_with(**settings)


def _after(**outcomes) -> evolver.ThisRun:
    return evolver.ThisRun(outcomes=dict(outcomes))


def _newly_sorted(*videos: str) -> dict:
    return {"sort": SortResult(moved=len(videos), moved_files=list(videos))}


@contextmanager
def _the_computer(*, pending=True, foreign_topaz=False, cpu_busy=False, signed_out=False,
                  upscaled=None, frozen=nullcontext):
    with ExitStack() as stack:
        yield SimpleNamespace(
            pending=stack.enter_context(
                patch("evolver.upscale.has_pending_work", return_value=pending)),
            foreign_topaz=stack.enter_context(
                patch("evolver.nonai_upscale.foreign_topaz_running", return_value=foreign_topaz)),
            frozen=stack.enter_context(
                patch("evolver.nonai_upscale.frozen_for_ai_videos", side_effect=frozen)),
            cpu_busy=stack.enter_context(
                patch("evolver._should_skip_upscale_due_to_cpu", return_value=cpu_busy)),
            signed_out=stack.enter_context(
                patch("util.topaz.sign_in_expired", return_value=signed_out)),
            upscale=stack.enter_context(
                patch("evolver.upscale.run", return_value=upscaled or UpscaleResult())),
        )


class TestTheUpscaleStage:
    def test_skips_with_its_reason_when_nothing_is_pending(self):
        with _the_computer(pending=False) as computer:
            outcome = _stage("upscale").run(_after(**_newly_sorted()))

        assert outcome == evolver.Skipped("no_pending_work")
        computer.upscale.assert_not_called()

    def test_waits_while_origenerator_trains_a_fix_on_the_graphics_card(self):
        with _the_computer() as computer:
            outcome = _stage("upscale").run(_after(
                **_newly_sorted("f"),
                origenerator_downtime=DowntimeResult(holds_the_graphics_card=True)))

        assert outcome == evolver.Skipped("origenerator_training")
        computer.upscale.assert_not_called()

    def test_waits_while_a_topaz_encode_evolver_did_not_start_is_running(self):
        with _the_computer(foreign_topaz=True) as computer:
            outcome = _stage("upscale").run(_after(**_newly_sorted("f")))

        assert outcome == evolver.Skipped("topaz_busy")
        computer.upscale.assert_not_called()
        computer.frozen.assert_not_called()

    def test_waits_while_the_computer_is_busy(self):
        with _the_computer(cpu_busy=True) as computer:
            outcome = _stage("upscale").run(_after(**_newly_sorted("new-file")))

        assert outcome == evolver.Skipped("cpu_busy")
        computer.upscale.assert_not_called()

    def test_waits_with_its_reason_while_topaz_is_signed_out(self):
        with _the_computer(signed_out=True) as computer:
            outcome = _stage("upscale").run(_after(**_newly_sorted("f")))

        assert outcome == evolver.Skipped(topaz.SIGN_IN_EXPIRED)
        computer.upscale.assert_not_called()

    def test_topaz_is_asked_about_its_sign_in_only_when_an_upscale_could_start(self):
        for held_back in ({"pending": False}, {"foreign_topaz": True}):
            with _the_computer(**held_back) as computer:
                _stage("upscale").run(_after(**_newly_sorted("f")))

            computer.signed_out.assert_not_called()

    def test_upscales_the_newly_sorted_videos_first_within_the_batch_limit(self):
        upscaled = UpscaleResult(processed=1)
        with _the_computer(upscaled=upscaled) as computer:
            outcome = _stage("upscale").run(_after(**_newly_sorted("new-file")))

        assert outcome is upscaled
        computer.upscale.assert_called_once_with(
            priority_files=["new-file"], max_items=config.UPSCALE_BATCH_LIMIT,
            listeners=evolver.upscale.Listeners(
                on_filed=evolver.origenerator_commands.write_the_gallery_entry_of_a_video_from),
        )

    def test_the_library_encode_is_frozen_around_every_topaz_step(self):
        steps = []

        @contextmanager
        def frozen():
            steps.append("frozen")
            yield
            steps.append("thawed")

        with _the_computer(frozen=frozen) as computer:
            computer.cpu_busy.side_effect = lambda log: steps.append("cpu sampled") and False
            computer.signed_out.side_effect = lambda: steps.append("sign-in asked") and False
            computer.upscale.side_effect = lambda **kwargs: steps.append("upscaled") or UpscaleResult()
            _stage("upscale").run(_after(**_newly_sorted("f")))

        assert steps == ["frozen", "cpu sampled", "sign-in asked", "upscaled", "thawed"]

    def test_it_reports_its_progress_under_its_own_name(self):
        progress = []

        def two_of_five(**kwargs):
            kwargs["listeners"].on_progress(1, 5)
            kwargs["listeners"].on_progress(2, 5)
            return UpscaleResult()

        with _the_computer() as computer:
            computer.upscale.side_effect = two_of_five
            _stage("upscale").run(evolver.ThisRun(
                outcomes=_newly_sorted("f"), on_progress=lambda *said: progress.append(said)))

        assert progress == [("upscale", 1, 5), ("upscale", 2, 5)]

    def test_without_a_progress_bar_it_keeps_the_upscales_own_listener(self):
        with _the_computer() as computer:
            _stage("upscale").run(_after(**_newly_sorted("f")))

        listeners = computer.upscale.call_args.kwargs["listeners"]
        assert listeners.on_progress is evolver.upscale.Listeners().on_progress


def _the_non_ai_mode(this_run: evolver.ThisRun, *, cpu_busy=False) -> nonai_upscale.RunMode:
    with patch("evolver.nonai_upscale.run", return_value=NonAiUpscaleResult()) as run, \
         patch("evolver._should_skip_upscale_due_to_cpu", return_value=cpu_busy):
        _stage("upscale_non_ai").run(this_run)
    return run.call_args.kwargs["mode"]


_NOTHING_PENDING = {"upscale": evolver.Skipped("no_pending_work")}


class TestTheNonAiUpscaleStage:
    def test_a_command_line_run_neither_starts_nor_stops_nor_manages_its_encodes(self):
        assert _the_non_ai_mode(_after(**_NOTHING_PENDING)) == nonai_upscale.RunMode(
            allow_start=False, stop=False, presence_managed=False,
            take_requests=False, ai_waiting=False)

    def test_switched_on_it_starts_once_the_ai_videos_are_done(self):
        this_run = evolver.ThisRun(nonai_enabled=True, outcomes=dict(_NOTHING_PENDING))

        assert _the_non_ai_mode(this_run) == nonai_upscale.RunMode(
            allow_start=True, stop=False, presence_managed=True,
            take_requests=True, ai_waiting=False)

    def test_switched_on_it_never_starts_while_ai_videos_remain(self):
        this_run = evolver.ThisRun(nonai_enabled=True,
                                   outcomes={"upscale": UpscaleResult(pending_after_run=2)})

        assert _the_non_ai_mode(this_run) == nonai_upscale.RunMode(
            allow_start=False, stop=False, presence_managed=True,
            take_requests=True, ai_waiting=True)

    def test_ai_videos_held_back_by_a_topaz_encode_evolver_did_not_start_are_still_waiting(self):
        this_run = evolver.ThisRun(nonai_enabled=True,
                                   outcomes={"upscale": evolver.Skipped("topaz_busy")})

        assert _the_non_ai_mode(this_run).ai_waiting is True

    def test_switched_on_it_never_starts_while_the_computer_is_busy(self):
        this_run = evolver.ThisRun(nonai_enabled=True, outcomes=dict(_NOTHING_PENDING))

        assert _the_non_ai_mode(this_run, cpu_busy=True) == nonai_upscale.RunMode(
            allow_start=False, stop=False, presence_managed=True,
            take_requests=True, ai_waiting=False)

    def test_switched_off_it_stops_the_encode_under_way(self):
        this_run = evolver.ThisRun(nonai_enabled=False, outcomes=dict(_NOTHING_PENDING))

        assert _the_non_ai_mode(this_run) == nonai_upscale.RunMode(
            allow_start=False, stop=True, presence_managed=False,
            take_requests=True, ai_waiting=False)


class TestTheCorrespondenceCheck:
    @pytest.mark.parametrize("upscaled", [
        pytest.param(evolver.Skipped("no_pending_work"), id="nothing was pending"),
        pytest.param(UpscaleResult(processed=2, pending_after_run=0), id="the upscale drained it"),
    ])
    def test_it_checks_with_its_popup_once_no_upscale_is_left(self, upscaled):
        checked = CorrespondenceResult(sorted_count=1, outbox_count=1)
        with patch("evolver.check_correspondence.run", return_value=checked) as check:
            outcome = _stage("verify").run(_after(upscale=upscaled))

        assert outcome is checked
        check.assert_called_once_with(show_popup=True)

    @pytest.mark.parametrize("upscaled", [
        pytest.param(UpscaleResult(processed=1, pending_after_run=1), id="videos still pending"),
        pytest.param(evolver.Skipped("cpu_busy"), id="the upscale held back"),
    ])
    def test_it_waits_while_videos_are_left_to_upscale(self, upscaled):
        with patch("evolver.check_correspondence.run") as check:
            outcome = _stage("verify").run(_after(upscale=upscaled))

        assert outcome == evolver.Skipped("upscale_pending")
        check.assert_not_called()


class TestEvolverMain:
    def _main(self, *stages: evolver.Stage, dependencies=None) -> int:
        with _a_lock_the_running_evolver_does_not_hold(), patch("evolver.setup_logging"), \
             patch("evolver.check_dependencies", dependencies or Mock()), \
             pytest.raises(SystemExit) as exited:
            evolver.main(stages=stages)
        return exited.value.code

    def test_exits_nonzero_on_dependency_check_failure(self):
        ran = []

        code = self._main(_made_up("first", run=lambda _: ran.append(1) or _Done()),
                          dependencies=Mock(side_effect=RuntimeError("ffprobe not found")))

        assert code == 1
        assert ran == []

    def test_a_dependency_failure_logs_the_failing_checks_traceback(self, caplog):
        def the_ffmpeg_check():
            raise RuntimeError("not found")

        with caplog.at_level(logging.ERROR):
            self._main(_made_up("first"), dependencies=the_ffmpeg_check)

        failures = [record for record in caplog.records
                    if "Dependency check failed" in record.getMessage()]
        assert len(failures) == 1
        assert failures[0].exc_info
        assert "the_ffmpeg_check" in logging.Formatter().formatException(failures[0].exc_info), (
            "which check raised is the whole of the diagnosis")

    def test_exits_zero_when_every_stage_went_well(self):
        assert self._main(_made_up("first"), _made_up("second")) == 0

    def test_a_stage_that_went_wrong_exits_nonzero(self):
        assert self._main(_made_up("first", run=lambda _: _Done(went_wrong=True))) == 1

    def test_exits_zero_when_a_stage_was_only_held_back(self):
        assert self._main(_made_up("first", run=lambda _: _Done(wants_an_eye=True)),
                          _made_up("second", run=lambda _: evolver.Skipped("cpu_busy"))) == 0


class TestCheckDependencies:
    def test_an_ffprobe_exiting_nonzero_raises_runtime_error(self):
        def ffprobe_exiting_nonzero(args, *, check, **_kwargs):
            if check:
                raise subprocess.CalledProcessError(1, args)
            return Mock(returncode=1)

        with patch("evolver.subprocess.run", ffprobe_exiting_nonzero), \
             patch("evolver.config.FFMPEG", Mock(is_file=Mock(return_value=True))), \
             pytest.raises(RuntimeError, match="ffprobe"):
            evolver.check_dependencies()

    def test_ffprobe_check_passes_create_no_window(self):
        with patch("evolver.subprocess.run") as mock_run, \
             patch("evolver.config.FFMPEG", Mock(is_file=Mock(return_value=True))):
            mock_run.return_value = Mock(returncode=0)
            evolver.check_dependencies()
            kwargs = mock_run.call_args.kwargs
            assert "creationflags" in kwargs
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


class TestCpuBusySkip:
    def _verdict(self, probe: Mock) -> bool:
        with patch("evolver.system_resources.measure_cpu_busy_percent", probe):
            return evolver._should_skip_upscale_due_to_cpu(logging.getLogger("test"))

    def test_skips_when_the_sample_reaches_the_threshold(self):
        assert self._verdict(Mock(return_value=config.CPU_BUSY_SKIP_THRESHOLD_PCT)) is True

    def test_runs_when_the_sample_is_under_the_threshold(self):
        assert self._verdict(Mock(return_value=config.CPU_BUSY_SKIP_THRESHOLD_PCT - 0.1)) is False

    def test_runs_when_the_probe_fails(self):
        assert self._verdict(Mock(side_effect=OSError("no counter"))) is False

    def test_samples_for_the_configured_window(self):
        probe = Mock(return_value=0.0)
        self._verdict(probe)
        probe.assert_called_once_with(config.CPU_BUSY_SKIP_SAMPLE_SECONDS)


@contextmanager
def _isolated_root_logger():
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
        root.handlers[:] = before
        root.setLevel(level)


class TestSetupLogging:
    def test_writes_the_log_when_something_configured_logging_first(self):
        with workspace_temp_dir() as folder, _isolated_root_logger() as root:
            root.addHandler(logging.NullHandler())
            log_file = folder / "evolver.log"
            with override_config(LOG_FILE=log_file):
                evolver.setup_logging()
            logging.getLogger("evolver.test").info("a line the pipeline wrote")
            for handler in root.handlers:
                handler.flush()

            assert "a line the pipeline wrote" in log_file.read_text(encoding="utf-8"), (
                "the error popups send him to this log")

    def test_a_second_run_does_not_write_every_line_twice(self):
        with workspace_temp_dir() as folder, _isolated_root_logger() as root:
            log_file = folder / "evolver.log"
            with override_config(LOG_FILE=log_file):
                evolver.setup_logging()
                evolver.setup_logging()
            logging.getLogger("evolver.test").info("one line")
            for handler in root.handlers:
                handler.flush()

            assert log_file.read_text(encoding="utf-8").count("one line") == 1


class TestTheWindowsDoorToTheQueue:
    def test_the_lineup_is_the_queues_own(self):
        with patch("tasks.nonai_upscale_queue.current") as queue:
            assert evolver.upscale_queue() is queue.return_value
        queue.assert_called_once_with()

    def test_rearranging_pins_the_videos_in_the_configured_pin_list(self):
        with patch("tasks.nonai_queue.pin_ahead") as pin_ahead, \
             override_config(NONAI_PIN_LIST=Path("next.txt")):
            evolver.arrange_upscale_queue(["lagoon/0 unsorted/a.mp4"])
        pin_ahead.assert_called_once_with(Path("next.txt"), ["lagoon/0 unsorted/a.mp4"])

    def test_asking_for_one_now_reaches_the_stage(self):
        with patch("tasks.nonai_request.request_now") as request_now:
            evolver.upscale_now("lagoon/0 unsorted/a.mp4")
        request_now.assert_called_once_with("lagoon/0 unsorted/a.mp4")

    def test_putting_one_first_reaches_the_stage(self):
        with patch("tasks.nonai_request.put_first") as put_first:
            evolver.upscale_next("lagoon/0 unsorted/a.mp4")
        put_first.assert_called_once_with("lagoon/0 unsorted/a.mp4")

    def test_withdrawing_the_ask_reaches_the_stage(self):
        with patch("tasks.nonai_request.withdraw_request") as withdraw_request:
            evolver.withdraw_upscale_now()
        withdraw_request.assert_called_once_with()


def _a_record_for(video: Path) -> Path:
    record = sidecar_path(video)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}", encoding="utf-8")
    return record


def _a_run(lib: LaneLibrary) -> None:
    with lib.config():
        _run(*_with_their_work_left_undone())


class TestWhatIsMarkedTrash:
    def test_a_run_leaves_a_flick_genau_marked_trash_where_it_is_with_its_record(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                marked = touch_video(lib.genau_trash / "loop_7_topaz.mp4")
                record = _a_record_for(lib.genau_flicks / marked.name)

            _a_run(lib)

            assert marked.exists()
            assert record.exists()

    def test_a_run_leaves_the_record_of_every_other_video_that_shares_its_name(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                touch_video(lib.genau_trash / "scene one.mp4")
                touch_video(lib.genau_trash / "loop_8_topaz.mp4")
                full_scene = _a_record_for(
                    touch_video(lib.non_ai / "example-bucket" / "full" / "scene one.mp4"))
                landscape_copy = _a_record_for(
                    touch_video(lib.outbox / "landscape" / "example-source" / "loop_8_topaz.mp4"))

            _a_run(lib)

            assert full_scene.exists()
            assert landscape_copy.exists()


class TestOneRunAtATime:
    def test_while_another_evolver_holds_the_turn_no_stage_runs(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            ran = []

            with override_config(PIPELINE_LOCK_FILE=lock), pytest.raises(run_lock.Busy):
                evolver.run_pipeline(stages=(_made_up("first", run=lambda _: ran.append(1)
                                                       or _Done()),))

            assert ran == []

    def test_the_turn_is_held_through_the_run_and_given_back(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            held_while_running = []

            with override_config(PIPELINE_LOCK_FILE=lock):
                evolver.run_pipeline(stages=(_made_up("first", run=lambda _: (
                    held_while_running.append(lock.exists()) or _Done())),))

            assert held_while_running == [True]
            assert not lock.exists()

    def test_a_command_line_run_that_finds_it_taken_says_so_and_fails(self, caplog):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")

            with override_config(PIPELINE_LOCK_FILE=lock), \
                 patch("evolver.setup_logging"), patch("evolver.check_dependencies"), \
                 caplog.at_level(logging.WARNING), pytest.raises(SystemExit) as exited:
                evolver.main(stages=(_made_up("first"),))

        assert exited.value.code == 1
        assert "running the pipeline" in caplog.text
