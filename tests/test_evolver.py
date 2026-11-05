from __future__ import annotations

import itertools
import logging
import os
import subprocess
import tempfile
import uuid
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import config
import evolver
from tasks import nonai_upscale
from tasks.stages import ALL_STAGES
from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir
from util import run_lock, run_log
from util.sidecar import sidecar_path

CRLF = (chr(13) + chr(10)).encode("ascii")


def _stage_mocks() -> dict:
    return {
        "strays_run": Mock(return_value=Mock(ok=True)),
        "sort_run": Mock(return_value=Mock(moved=0, moved_files=[])),
        "withdrawn_run": Mock(return_value=Mock(failed=0)),
        "scripts_sync_run": Mock(return_value=Mock(ok=True, not_checked=0)),
        "bookmarks_sync_run": Mock(return_value=Mock(ok=True)),
        "prompt_scrape_run": Mock(return_value=Mock(ok=True)),
        "origenerator_downtime_run": Mock(return_value=Mock(holds_the_graphics_card=False,
                                                            failed=False)),
        "upscale_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=0)),
        "genau_deliver_run": Mock(return_value=Mock(failed=0)),
        "nonai_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, unreachable_archive="")),
        "nonai_group_run": Mock(),
        "nonai_titles_run": Mock(),
        "video_types_run": Mock(),
        "provenance_sweep_run": Mock(),
        "clip_scripts_run": Mock(),
        "scene_scripts_run": Mock(),
        "reference_sync_run": Mock(return_value=Mock(ok=True)),
        "watch_weights_run": Mock(return_value=Mock(ok=True)),
        "duplicate_sizes_run": Mock(return_value=Mock(ok=True)),
        "correspondence_run": Mock(return_value=Mock(ok=True)),
        "has_pending_work": Mock(return_value=False),
        "should_skip_cpu": Mock(return_value=False),
        "foreign_topaz_running": Mock(return_value=False),
        "frozen_for_ai_videos": Mock(side_effect=nullcontext),
        "topaz_sign_in_expired": Mock(return_value=False),
    }


_STAGE_PATCHES = [
    ("evolver.stray_files.run", "strays_run"),
    ("evolver.sort.run", "sort_run"),
    ("evolver.origenerator_commands.run_downtime", "origenerator_downtime_run"),
    ("evolver.video_kinds.run", "video_types_run"),
    ("evolver.provenance_sweep.run", "provenance_sweep_run"),
    ("evolver.taken_back.run", "withdrawn_run"),
    ("evolver.clip_scripts.run", "clip_scripts_run"),
    ("evolver.scene_scripts.run", "scene_scripts_run"),
    ("evolver.scripts_sync.run", "scripts_sync_run"),
    ("evolver.upscale.run", "upscale_run"),
    ("evolver.genau_deliver.run", "genau_deliver_run"),
    ("evolver.nonai_upscale.run", "nonai_run"),
    ("evolver.nonai_group.run", "nonai_group_run"),
    ("evolver.nonai_titles.run", "nonai_titles_run"),
    ("evolver.reference_sync.run", "reference_sync_run"),
    ("evolver.watch_weights.run", "watch_weights_run"),
    ("evolver.bookmarks_sync.run", "bookmarks_sync_run"),
    ("evolver.check_correspondence.run", "correspondence_run"),
    ("evolver.check_duplicate_sizes.run", "duplicate_sizes_run"),
    ("evolver.upscale.has_pending_work", "has_pending_work"),
    ("evolver._should_skip_upscale_due_to_cpu", "should_skip_cpu"),
    ("evolver.nonai_upscale.foreign_topaz_running", "foreign_topaz_running"),
    ("evolver.nonai_upscale.frozen_for_ai_videos", "frozen_for_ai_videos"),
    ("util.topaz.sign_in_expired", "topaz_sign_in_expired"),
    ("evolver.prompt_scrape.run", "prompt_scrape_run"),
]


def _patched_stages(mocks: dict) -> ExitStack:
    stack = ExitStack()
    for target, key in _STAGE_PATCHES:
        stack.enter_context(patch(target, mocks[key]))
    stack.enter_context(override_config(
        PIPELINE_LOCK_FILE=Path(tempfile.gettempdir()) / "evolver-tests"
        / f"pipeline-{uuid.uuid4().hex}.lock"))
    return stack


_EXPECTED_STAGE_ORDER = ALL_STAGES


class TestEvolverMain:
    def _run_pipeline(self, **overrides):
        mocks = _stage_mocks() | {"setup_logging": Mock(), "check_dependencies": Mock()}
        mocks.update(overrides)

        with _patched_stages(mocks) as stack:
            stack.enter_context(patch("evolver.setup_logging", mocks["setup_logging"]))
            stack.enter_context(patch("evolver.check_dependencies", mocks["check_dependencies"]))
            with pytest.raises(SystemExit) as exc:
                evolver.main()

        mocks["exit_code"] = exc.value.code
        return mocks

    def test_exits_nonzero_on_dependency_check_failure(self):
        mocks = self._run_pipeline(
            check_dependencies=Mock(side_effect=RuntimeError("ffprobe not found")),
        )
        assert mocks["exit_code"] == 1
        mocks["sort_run"].assert_not_called()

    def test_a_dependency_failure_is_logged_with_its_traceback(self, caplog):
        with caplog.at_level(logging.ERROR):
            self._run_pipeline(
                check_dependencies=Mock(side_effect=RuntimeError("ffprobe not found")),
            )

        failures = [record for record in caplog.records
                    if "Dependency check failed" in record.getMessage()]
        assert failures
        assert all(record.exc_info for record in failures)

    def test_skips_upscale_when_no_pending_work(self):
        mocks = self._run_pipeline()
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_called_once_with(show_popup=True)

    def test_skips_correspondence_when_upscale_has_pending(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=3, moved_files=["a", "b", "c"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=1)),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_called_once()
        mocks["correspondence_run"].assert_not_called()

    def test_skips_upscale_and_correspondence_when_cpu_busy(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
            has_pending_work=Mock(return_value=True),
            should_skip_cpu=Mock(return_value=True),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_not_called()

    def test_runs_upscale_with_priority_files(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
            has_pending_work=Mock(return_value=True),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_called_once_with(
            priority_files=["new-file"], max_items=config.UPSCALE_BATCH_LIMIT,
            listeners=evolver.upscale.Listeners(
                on_filed=evolver.origenerator_commands.write_the_gallery_entry_of_a_video_from),
        )

    def test_watch_weights_tells_origenerators_gallery_what_the_records_hold(self):
        mocks = self._run_pipeline()

        mocks["watch_weights_run"].assert_called_once_with(
            tell_the_gallery=evolver.origenerator_commands.write_gallery_entries)

    def test_ai_upscale_waits_while_a_topaz_encode_evolver_did_not_start_is_running(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            foreign_topaz_running=Mock(return_value=True),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_not_called()
        mocks["frozen_for_ai_videos"].assert_not_called()
        mocks["correspondence_run"].assert_not_called()

    def test_ai_upscale_waits_while_origenerator_trains_a_fix_on_the_graphics_card(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            origenerator_downtime_run=Mock(return_value=Mock(holds_the_graphics_card=True,
                                                             failed=False)),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_not_called()

    def test_ai_videos_upscale_with_the_library_encode_frozen_around_every_topaz_step(self):
        steps = []

        @contextmanager
        def frozen():
            steps.append("frozen")
            yield
            steps.append("thawed")

        self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            frozen_for_ai_videos=Mock(side_effect=frozen),
            should_skip_cpu=Mock(side_effect=lambda log: steps.append("cpu sampled") and False),
            topaz_sign_in_expired=Mock(side_effect=lambda: steps.append("sign-in asked") and False),
            upscale_run=Mock(side_effect=lambda **kwargs: steps.append("upscaled") or Mock(
                failed=0, deferred_low_disk=False, pending_after_run=0)),
        )

        assert steps == ["frozen", "cpu sampled", "sign-in asked", "upscaled", "thawed"]

    def test_cli_run_neither_starts_nor_stops_nor_manages_nonai_encodes(self):
        mocks = self._run_pipeline()
        mocks["nonai_run"].assert_called_once_with(
            mode=nonai_upscale.RunMode(
                allow_start=False, stop=False, presence_managed=False,
                take_requests=False, ai_waiting=False))

    @pytest.mark.parametrize(
        "failing_overrides",
        [
            pytest.param(lambda: {
                "withdrawn_run": Mock(return_value=Mock(failed=1))}, id="withdrawn"),
            pytest.param(lambda: {
                "nonai_run": Mock(return_value=Mock(failed=1, deferred_low_disk=False))}, id="upscale_non_ai"),
            pytest.param(lambda: {
                "sort_run": Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
                "has_pending_work": Mock(return_value=True),
                "correspondence_run": Mock(return_value=Mock(ok=False))}, id="verify"),
            pytest.param(lambda: {
                "duplicate_sizes_run": Mock(return_value=Mock(ok=False))}, id="dupes"),
            pytest.param(lambda: {
                "scripts_sync_run": Mock(return_value=Mock(ok=False))}, id="scripts"),
            pytest.param(lambda: {
                "bookmarks_sync_run": Mock(return_value=Mock(ok=False))}, id="bookmarks"),
            pytest.param(lambda: {
                "sort_run": Mock(return_value=Mock(moved=1, moved_files=["f"])),
                "has_pending_work": Mock(return_value=True),
                "upscale_run": Mock(return_value=Mock(
                    failed=2, deferred_low_disk=False, pending_after_run=0))}, id="upscale"),
            pytest.param(lambda: {
                "prompt_scrape_run": Mock(return_value=Mock(ok=False))}, id="metadata"),
        ],
    )
    def test_a_failing_stage_exits_nonzero(self, failing_overrides):
        mocks = self._run_pipeline(**failing_overrides())
        assert mocks["exit_code"] == 1

    def test_exits_zero_when_upscale_only_held_back_for_low_disk(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=True, pending_after_run=3)),
        )
        assert mocks["exit_code"] == 0

    def test_all_stages_called_on_clean_run_with_pending_work(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
        )
        assert mocks["exit_code"] == 0
        mocks["sort_run"].assert_called_once()
        mocks["withdrawn_run"].assert_called_once()
        mocks["clip_scripts_run"].assert_called_once()
        mocks["scripts_sync_run"].assert_called_once_with(show_popup=True)
        mocks["bookmarks_sync_run"].assert_called_once()
        mocks["prompt_scrape_run"].assert_called_once()
        mocks["upscale_run"].assert_called_once()
        mocks["duplicate_sizes_run"].assert_called_once_with(show_popup=True)
        mocks["correspondence_run"].assert_called_once_with(show_popup=True)


class TestRunPipeline:
    def _patch_all_stages(self, **overrides):
        defaults = _stage_mocks()
        defaults.update(overrides)
        return _patched_stages(defaults), defaults

    def test_every_stage_the_pipeline_runs_is_a_stub_from_the_mock_table(self):
        stack, _ = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
        )
        with stack:
            result = evolver.run_pipeline()
        assert len(result.stages) == len(ALL_STAGES)
        for stage in result.stages:
            assert stage.status != "skipped", \
                f"stage {stage.name!r} must actually run in this test"
            assert isinstance(stage.result, Mock), (
                f"stage {stage.name!r} ran its real function -- add it to "
                "_stage_mocks and _STAGE_PATCHES"
            )

    def test_a_clean_run_reports_every_stage_it_ran_and_no_errors(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        assert isinstance(result, evolver.PipelineResult)
        assert not result.has_errors
        assert len(result.stages) > 0

    def test_the_run_marks_where_in_the_log_it_wrote(self, tmp_path):
        log = tmp_path / "evolver.log"
        log.write_bytes(b"[2026-07-25 08:10:02] an earlier run" + CRLF)
        stack, _ = self._patch_all_stages()
        handler = logging.FileHandler(log, encoding="utf-8")
        logger = logging.getLogger("evolver")
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with stack, patch.object(config, "LOG_FILE", log):
                result = evolver.run_pipeline()
        finally:
            logger.setLevel(previous_level)
            logger.removeHandler(handler)
            handler.close()

        text = run_log.read_run(log, run_log.run_id(result.started_at),
                                result.log_start, result.log_end)
        assert text is not None
        assert "an earlier run" not in text

    def test_a_log_it_cannot_measure_leaves_the_mark_unset(self):
        missing = Path("no-such-directory") / "evolver.log"
        stack, _ = self._patch_all_stages()
        with stack, patch.object(config, "LOG_FILE", missing):
            result = evolver.run_pipeline()

        assert (result.log_start, result.log_end) == (None, None)

    def test_stage_records_have_correct_names(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        assert names == _EXPECTED_STAGE_ORDER

    def test_the_phone_s_favorites_are_marked_before_bookmarks_reads_the_marks(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        assert names.index("watch_weights") < names.index("bookmarks")

    def test_skipped_stages_have_skip_status(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        upscale_stage = next(s for s in result.stages if s.name == "upscale")
        assert upscale_stage.status == "skipped"
        assert upscale_stage.skip_reason == "no_pending_work"

    def test_upscaling_waits_with_its_reason_while_topaz_is_signed_out(self):
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            topaz_sign_in_expired=Mock(return_value=True),
        )
        with stack:
            result = evolver.run_pipeline()
        upscale_stage = next(s for s in result.stages if s.name == "upscale")
        assert upscale_stage.skip_reason == "topaz_sign_in_expired"
        mocks["upscale_run"].assert_not_called()

    def test_topaz_is_asked_about_its_sign_in_only_when_an_upscale_could_start(self):
        for overrides in (
            {"has_pending_work": Mock(return_value=False)},
            {"has_pending_work": Mock(return_value=True),
                 "foreign_topaz_running": Mock(return_value=True)},
        ):
            stack, mocks = self._patch_all_stages(**overrides)
            with stack:
                evolver.run_pipeline()
            mocks["topaz_sign_in_expired"].assert_not_called()

    def test_on_stage_start_called_for_each_stage(self):
        on_start = Mock()
        stack, _ = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_start=on_start)
        started_names = [call.args[0] for call in on_start.call_args_list]
        assert started_names == _EXPECTED_STAGE_ORDER

    def test_on_stage_complete_called_with_result_and_status(self):
        on_complete = Mock()
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_complete=on_complete)
        withdrawn_call = next(c for c in on_complete.call_args_list if c.args[0] == "withdrawn")
        assert withdrawn_call.args[1] == mocks["withdrawn_run"].return_value
        assert isinstance(withdrawn_call.args[2], float)
        assert withdrawn_call.args[3] == "completed"

    def test_on_stage_complete_reports_skipped_for_upscale(self):
        on_complete = Mock()
        stack, _ = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_complete=on_complete)
        upscale_call = next(c for c in on_complete.call_args_list if c.args[0] == "upscale")
        assert upscale_call.args[1] is None
        assert upscale_call.args[3] == "skipped"

    def test_enabled_nonai_upscale_starts_when_ai_work_is_drained(self):
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            mode=nonai_upscale.RunMode(
                allow_start=True, stop=False, presence_managed=True,
                take_requests=True, ai_waiting=False))

    def test_enabled_nonai_upscale_never_starts_while_ai_work_remains(self):
        stack, mocks = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=2)),
        )
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            mode=nonai_upscale.RunMode(
                allow_start=False, stop=False, presence_managed=True,
                take_requests=True, ai_waiting=True))

    def test_ai_videos_held_back_by_a_topaz_encode_evolver_did_not_start_are_still_waiting(self):
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            foreign_topaz_running=Mock(return_value=True),
        )
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        assert mocks["nonai_run"].call_args.kwargs["mode"].ai_waiting is True

    def test_enabled_nonai_upscale_never_starts_when_cpu_is_busy(self):
        stack, mocks = self._patch_all_stages(
            should_skip_cpu=Mock(return_value=True),
        )
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            mode=nonai_upscale.RunMode(
                allow_start=False, stop=False, presence_managed=True,
                take_requests=True, ai_waiting=False))

    def test_disabled_nonai_upscale_stops_the_in_flight_encode(self):
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(nonai_enabled=False)
        mocks["nonai_run"].assert_called_once_with(
            mode=nonai_upscale.RunMode(
                allow_start=False, stop=True, presence_managed=False,
                take_requests=True, ai_waiting=False))

    def test_has_errors_true_when_stage_fails(self):
        stack, _ = self._patch_all_stages(
            withdrawn_run=Mock(return_value=Mock(failed=1)),
        )
        with stack:
            result = evolver.run_pipeline()
        assert result.has_errors

    def test_the_failing_stage_is_the_one_marked_error(self):
        stack, _ = self._patch_all_stages(
            withdrawn_run=Mock(return_value=Mock(failed=1)),
        )
        with stack:
            result = evolver.run_pipeline()
        errored = [s.name for s in result.stages if s.status == "error"]
        assert errored == ["withdrawn"]

    def test_a_low_disk_hold_warns_on_the_non_ai_stage_instead_of_failing_it(self):
        stack, _ = self._patch_all_stages(
            nonai_run=Mock(return_value=Mock(failed="", deferred_low_disk=True)),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale_non_ai"] == "warning"
        assert not result.has_errors

    def test_scripts_left_unchecked_while_a_folder_cannot_be_reached_warn_instead_of_failing(self):
        stack, _ = self._patch_all_stages(
            scripts_sync_run=Mock(return_value=Mock(ok=True, not_checked=15)),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["scripts"] == "warning"
        assert not result.has_errors

    def test_a_finished_encode_waiting_for_the_archive_warns_instead_of_failing(self):
        stack, _ = self._patch_all_stages(
            nonai_run=Mock(return_value=Mock(failed="", deferred_low_disk=False,
                                             unreachable_archive="Q:/archive")),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale_non_ai"] == "warning"
        assert not result.has_errors

    def test_a_dead_encode_outranks_a_hold_on_the_same_stage(self):
        stack, _ = self._patch_all_stages(
            nonai_run=Mock(return_value=Mock(failed="example/clip one.mp4",
                                             deferred_low_disk=True)),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale_non_ai"] == "error"

    def test_skips_alone_do_not_make_a_run_a_failure(self):
        stack, _ = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            foreign_topaz_running=Mock(return_value=True),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale"] == "skipped"
        assert statuses["verify"] == "skipped"
        assert not result.has_errors

    def test_duration_seconds_is_positive(self):
        ticks = itertools.count(start=1.0, step=1.0)
        stack, _ = self._patch_all_stages()
        with stack, patch("evolver.time.monotonic", lambda: next(ticks)):
            result = evolver.run_pipeline()
        assert result.duration_seconds > 0.0

    def test_on_stage_progress_forwarded_to_upscale(self):
        on_progress = Mock()
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
        )
        with stack:
            evolver.run_pipeline(on_stage_progress=on_progress)
        mocks["upscale_run"].call_args.kwargs["listeners"].on_progress(1, 5)
        on_progress.assert_called_once_with("upscale", 1, 5)

    def test_on_stage_progress_not_passed_when_none(self):
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
        )
        with stack:
            evolver.run_pipeline(on_stage_progress=None)
        listeners = mocks["upscale_run"].call_args.kwargs["listeners"]
        assert listeners.on_progress is evolver.upscale.Listeners().on_progress

    def test_on_stage_progress_callback_binds_stage_name(self):
        progress_calls = []

        def capture_upscale_run(**kwargs):
            kwargs["listeners"].on_progress(1, 5)
            kwargs["listeners"].on_progress(2, 5)
            return Mock(failed=0, deferred_low_disk=False, pending_after_run=0)

        stack, _ = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            upscale_run=Mock(side_effect=capture_upscale_run),
        )
        with stack:
            evolver.run_pipeline(
                on_stage_progress=lambda name, cur, tot: progress_calls.append((name, cur, tot)),
            )
        assert progress_calls == [("upscale", 1, 5), ("upscale", 2, 5)]


class TestCooperativeStop:
    def test_stops_between_stages_once_asked(self):
        completed: list[str] = []
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline(
                on_stage_complete=lambda name, *_: completed.append(name),
                should_stop=lambda: bool(completed),
            )

        assert [s.name for s in result.stages] == ALL_STAGES[:1]

    def test_a_stop_that_is_never_requested_changes_nothing(self):
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline(should_stop=lambda: False)

        assert len(result.stages) == len(ALL_STAGES)


class TestCheckDependenciesWindowSuppression:
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
    def test_writes_the_log_even_when_something_configured_logging_first(self):
        with workspace_temp_dir() as folder, _isolated_root_logger() as root:
            root.addHandler(logging.NullHandler())
            log_file = folder / "evolver.log"
            with override_config(LOG_FILE=log_file):
                evolver.setup_logging()
            logging.getLogger("evolver.test").info("a line the pipeline wrote")
            for handler in root.handlers:
                handler.flush()

            assert "a line the pipeline wrote" in log_file.read_text(encoding="utf-8")

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
    with lib.config(), _patched_stages(_stage_mocks()):
        evolver.run_pipeline()


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
            mocks = _stage_mocks()

            with _patched_stages(mocks), override_config(PIPELINE_LOCK_FILE=lock), \
                 pytest.raises(run_lock.Busy):
                evolver.run_pipeline()

            mocks["strays_run"].assert_not_called()

    def test_the_turn_is_held_through_the_run_and_given_back(self):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            held_while_running = []
            mocks = _stage_mocks()
            mocks["strays_run"] = Mock(side_effect=lambda: (
                held_while_running.append(lock.exists()) or Mock(ok=True)))

            with _patched_stages(mocks), override_config(PIPELINE_LOCK_FILE=lock):
                evolver.run_pipeline()

            assert held_while_running == [True]
            assert not lock.exists()

    def test_a_command_line_run_that_finds_it_taken_says_so_and_fails(self, caplog):
        with workspace_temp_dir() as root:
            lock = root / "pipeline.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")

            with _patched_stages(_stage_mocks()), override_config(PIPELINE_LOCK_FILE=lock), \
                 patch("evolver.setup_logging"), patch("evolver.check_dependencies"), \
                 caplog.at_level(logging.WARNING), pytest.raises(SystemExit) as exited:
                evolver.main()

        assert exited.value.code == 1
        assert "running the pipeline" in caplog.text
