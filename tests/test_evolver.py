import itertools
import logging
import subprocess
from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest

import config
import evolver
from tasks.stages import ALL_STAGES


def _stage_mocks() -> dict:
    """A stand-in for every stage the pipeline calls.

    One list, used by both helpers below, so a newly added stage is stubbed
    everywhere at once. A stage left off it runs for real against the live
    library and the sibling apps' saved state, which turns a unit test into a
    maintenance run.
    """
    return {
        "strays_run": Mock(return_value=Mock(ok=True)),
        "sort_run": Mock(return_value=Mock(moved=0, moved_files=[])),
        "purge_run": Mock(return_value=Mock(missing_sorted=[])),
        "scripts_sync_run": Mock(return_value=Mock(ok=True)),
        "bookmarks_sync_run": Mock(return_value=Mock(ok=True)),
        "prompt_scrape_run": Mock(return_value=Mock(ok=True)),
        "upscale_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=0)),
        "genau_deliver_run": Mock(return_value=Mock(failed=0)),
        "nonai_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False)),
        "nonai_group_run": Mock(),
        "clip_scripts_run": Mock(),
        "scene_scripts_run": Mock(),
        "reference_sync_run": Mock(return_value=Mock(ok=True)),
        "duplicate_sizes_run": Mock(return_value=Mock(ok=True)),
        "correspondence_run": Mock(return_value=Mock(ok=True)),
        "has_pending_work": Mock(return_value=False),
        "should_skip_cpu": Mock(return_value=False),
        "count_running": Mock(return_value=0),
    }


_STAGE_PATCHES = [
    ("evolver.stray_files.run", "strays_run"),
    ("evolver.sort.run", "sort_run"),
    ("evolver.purge_weird.run", "purge_run"),
    ("evolver.clip_scripts.run", "clip_scripts_run"),
    ("evolver.scene_scripts.run", "scene_scripts_run"),
    ("evolver.scripts_sync.run", "scripts_sync_run"),
    ("evolver.upscale.run", "upscale_run"),
    ("evolver.genau_deliver.run", "genau_deliver_run"),
    ("evolver.nonai_upscale.run", "nonai_run"),
    ("evolver.nonai_group.run", "nonai_group_run"),
    ("evolver.reference_sync.run", "reference_sync_run"),
    ("evolver.bookmarks_sync.run", "bookmarks_sync_run"),
    ("evolver.check_correspondence.run", "correspondence_run"),
    ("evolver.check_duplicate_sizes.run", "duplicate_sizes_run"),
    ("evolver.upscale.has_pending_work", "has_pending_work"),
    ("evolver._should_skip_upscale_due_to_cpu", "should_skip_cpu"),
    ("evolver.processes.count_running", "count_running"),
    ("evolver.prompt_scrape.run", "prompt_scrape_run"),
]


def _patched_stages(mocks: dict) -> ExitStack:
    stack = ExitStack()
    for target, key in _STAGE_PATCHES:
        stack.enter_context(patch(target, mocks[key]))
    return stack


# The pipeline's stage order has one home, tasks/stages.py, and these
# tests read it rather than keeping a second copy. It was a second copy while
# the registry was missing genau_deliver, since deriving from it would have
# encoded that bug here too; tests/test_stage_registry.py is what holds the
# two in step now.
_EXPECTED_STAGE_ORDER = ALL_STAGES


class TestEvolverMain:
    """Tests for the evolver.main() pipeline orchestration."""

    def _run_pipeline(self, **overrides):
        """Run evolver.main() with all stages mocked.

        Returns a dict of mock objects keyed by stage name. Callers can
        pre-configure mocks via **overrides before the run, e.g.:

            mocks = self._run_pipeline(
                correspondence_run=Mock(return_value=Mock(ok=False)),
            )
        """
        mocks = _stage_mocks() | {"setup_logging": Mock(), "check_dependencies": Mock()}
        mocks.update(overrides)

        with _patched_stages(mocks) as stack:
            stack.enter_context(patch("evolver.setup_logging", mocks["setup_logging"]))
            stack.enter_context(patch("evolver.check_dependencies", mocks["check_dependencies"]))
            with pytest.raises(SystemExit) as exc:
                evolver.main()

        mocks["exit_code"] = exc.value.code
        return mocks

    # --- Dependency check ---

    def test_exits_nonzero_on_dependency_check_failure(self):
        mocks = self._run_pipeline(
            check_dependencies=Mock(side_effect=RuntimeError("ffprobe not found")),
        )
        assert mocks["exit_code"] == 1
        mocks["sort_run"].assert_not_called()

    def test_a_dependency_failure_is_logged_with_its_traceback(self, caplog):
        """Which of the checks raised is the whole content of the diagnosis, and
        only the traceback names it -- the message reads "Dependency check
        failed" either way."""
        with caplog.at_level(logging.ERROR):
            self._run_pipeline(
                check_dependencies=Mock(side_effect=RuntimeError("ffprobe not found")),
            )

        failures = [record for record in caplog.records
                    if "Dependency check failed" in record.getMessage()]
        assert failures
        assert all(record.exc_info for record in failures)

    # --- Stage sequencing ---

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
        )

    # --- Non-AI upscale gating ---

    def test_ai_upscale_waits_while_a_topaz_encode_is_running(self):
        """A detached non-AI encode (or a manual GUI export) owns the GPU;
        stacking the AI batch on top is what crashed the machine."""
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            count_running=Mock(return_value=1),
        )
        assert mocks["exit_code"] == 0
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_not_called()

    def test_cli_run_neither_starts_nor_stops_nor_manages_nonai_encodes(self):
        mocks = self._run_pipeline()
        mocks["nonai_run"].assert_called_once_with(
            allow_start=False, stop=False, presence_managed=False)

    # --- Exit code propagation ---

    @pytest.mark.parametrize(
        "failing_overrides",
        [
            pytest.param(lambda: dict(
                purge_run=Mock(return_value=Mock(missing_sorted=["file.mp4"]))), id="purge"),
            pytest.param(lambda: dict(
                nonai_run=Mock(return_value=Mock(failed=1, deferred_low_disk=False))), id="upscale_non_ai"),
            pytest.param(lambda: dict(
                sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
                has_pending_work=Mock(return_value=True),
                correspondence_run=Mock(return_value=Mock(ok=False))), id="verify"),
            pytest.param(lambda: dict(
                duplicate_sizes_run=Mock(return_value=Mock(ok=False))), id="dupes"),
            pytest.param(lambda: dict(
                scripts_sync_run=Mock(return_value=Mock(ok=False))), id="scripts"),
            pytest.param(lambda: dict(
                bookmarks_sync_run=Mock(return_value=Mock(ok=False))), id="bookmarks"),
            pytest.param(lambda: dict(
                sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
                has_pending_work=Mock(return_value=True),
                upscale_run=Mock(return_value=Mock(
                    failed=2, deferred_low_disk=False, pending_after_run=0))), id="upscale"),
            pytest.param(lambda: dict(
                prompt_scrape_run=Mock(return_value=Mock(ok=False))), id="metadata"),
        ],
    )
    def test_a_failing_stage_exits_nonzero(self, failing_overrides):
        """Eight longhand tests differing only in which mock failed, as a table.

        The overrides come from factories so each case gets fresh Mocks.
        """
        mocks = self._run_pipeline(**failing_overrides())
        assert mocks["exit_code"] == 1

    def test_exits_zero_when_upscale_only_held_back_for_low_disk(self):
        """A hold is not a failure: nothing broke, there is just no room yet."""
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=True, pending_after_run=3)),
        )
        assert mocks["exit_code"] == 0

    # --- All stages called on clean run ---

    def test_all_stages_called_on_clean_run_with_pending_work(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
        )
        assert mocks["exit_code"] == 0
        mocks["sort_run"].assert_called_once()
        mocks["purge_run"].assert_called_once()
        mocks["clip_scripts_run"].assert_called_once()
        mocks["scripts_sync_run"].assert_called_once_with(show_popup=True)
        mocks["bookmarks_sync_run"].assert_called_once()
        mocks["prompt_scrape_run"].assert_called_once()
        mocks["upscale_run"].assert_called_once()
        mocks["duplicate_sizes_run"].assert_called_once_with(show_popup=True)
        mocks["correspondence_run"].assert_called_once_with(show_popup=True)


class TestRunPipeline:
    """Tests for evolver.run_pipeline() and its callback protocol."""

    def _patch_all_stages(self, **overrides):
        """Return an ExitStack context that patches all stages for run_pipeline()."""
        defaults = _stage_mocks()
        defaults.update(overrides)
        return _patched_stages(defaults), defaults

    def test_every_stage_the_pipeline_runs_is_a_stub_from_the_mock_table(self):
        """The invariant _stage_mocks' docstring states, made enforceable.

        A stage missing from the table runs for real against whatever library
        the overlay resolves to — genau_deliver was missing for months and 38
        tests ran a real move-and-delete stage, kept inert only by the example
        overlay's placeholder path. Driving every stage to actually run and
        demanding a Mock result catches the next stage added without a stub.
        """
        stack, _ = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
        )
        with stack:
            result = evolver.run_pipeline()
        assert len(result.stages) == 15
        for stage in result.stages:
            assert stage.status != "skipped", \
                f"stage {stage.name!r} must actually run in this test"
            assert isinstance(stage.result, Mock), (
                f"stage {stage.name!r} ran its real function -- add it to "
                "_stage_mocks and _STAGE_PATCHES"
            )

    def test_returns_pipeline_result(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        assert isinstance(result, evolver.PipelineResult)
        assert not result.has_errors
        assert len(result.stages) > 0

    def test_stage_records_have_correct_names(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        assert names == _EXPECTED_STAGE_ORDER

    def test_references_run_before_bookmarks_prunes_the_favorites(self):
        """Both stages touch favs.csv, and bookmarks drops rows whose file is gone.

        Repointing has to come first, or a favorite whose video merely moved is
        deleted on the very run that could have saved it.
        """
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        assert names.index("references") < names.index("bookmarks")

    def test_skipped_stages_have_skip_status(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        upscale_stage = next(s for s in result.stages if s.name == "upscale")
        assert upscale_stage.status == "skipped"
        assert upscale_stage.skip_reason == "no_pending_work"

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
        # Any stage would do; purge is picked by name rather than by position,
        # because its position is the registry's to decide.
        purge_call = next(c for c in on_complete.call_args_list if c.args[0] == "purge")
        assert purge_call.args[1] == mocks["purge_run"].return_value
        assert isinstance(purge_call.args[2], float)  # elapsed
        assert purge_call.args[3] == "completed"

    def test_on_stage_complete_reports_skipped_for_upscale(self):
        on_complete = Mock()
        stack, _ = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_complete=on_complete)
        upscale_call = next(c for c in on_complete.call_args_list if c.args[0] == "upscale")
        assert upscale_call.args[1] is None  # no result
        assert upscale_call.args[3] == "skipped"

    def test_enabled_nonai_upscale_starts_when_ai_work_is_drained(self):
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            allow_start=True, stop=False, presence_managed=True)

    def test_enabled_nonai_upscale_never_starts_while_ai_work_remains(self):
        stack, mocks = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=2)),
        )
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            allow_start=False, stop=False, presence_managed=True)

    def test_enabled_nonai_upscale_never_starts_when_cpu_is_busy(self):
        stack, mocks = self._patch_all_stages(
            should_skip_cpu=Mock(return_value=True),
        )
        with stack:
            evolver.run_pipeline(nonai_enabled=True)
        mocks["nonai_run"].assert_called_once_with(
            allow_start=False, stop=False, presence_managed=True)

    def test_disabled_nonai_upscale_stops_the_in_flight_encode(self):
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(nonai_enabled=False)
        mocks["nonai_run"].assert_called_once_with(
            allow_start=False, stop=True, presence_managed=False)

    def test_has_errors_true_when_stage_fails(self):
        stack, _ = self._patch_all_stages(
            purge_run=Mock(return_value=Mock(missing_sorted=["file.mp4"])),
        )
        with stack:
            result = evolver.run_pipeline()
        assert result.has_errors

    def test_the_failing_stage_is_the_one_marked_error(self):
        """A run's verdict has to be legible in the stage list it ships with.

        Every stage used to record "completed" the moment its function returned,
        while the run's verdict was computed separately from the result payloads
        — so a run read "error" with twelve stages all reading "completed" and
        nothing anywhere saying which one went wrong.
        """
        stack, _ = self._patch_all_stages(
            purge_run=Mock(return_value=Mock(missing_sorted=["file.mp4"])),
        )
        with stack:
            result = evolver.run_pipeline()
        errored = [s.name for s in result.stages if s.status == "error"]
        assert errored == ["purge"]

    def test_a_low_disk_hold_warns_on_the_non_ai_stage_instead_of_failing_it(self):
        """The condition that reddened almost every run for days on end.

        Free space fell under the floor, the non-AI stage held its encode back,
        and the run was flagged an error. Space stays low for days at a stretch,
        so that verdict left the history a wall of red crosses standing over a
        condition nobody has to act on. The stage names the hold itself now, and
        names it in gray.
        """
        stack, _ = self._patch_all_stages(
            nonai_run=Mock(return_value=Mock(failed="", deferred_low_disk=True)),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale_non_ai"] == "warning"
        assert not result.has_errors

    def test_a_dead_encode_outranks_a_hold_on_the_same_stage(self):
        """One tick can lose an encode and then find no room for the next. The
        lost encode wants a person; the hold only wants disk space."""
        stack, _ = self._patch_all_stages(
            nonai_run=Mock(return_value=Mock(failed="example/clip one.mp4",
                                             deferred_low_disk=True)),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale_non_ai"] == "error"

    def test_skips_alone_do_not_make_a_run_a_failure(self):
        """Skipping is how the pipeline stays out of the way, not how it fails.

        A Topaz encode already owning the GPU parks the AI upscale, which parks
        the correspondence check behind it — two skipped stages on a run where
        nothing at all went wrong.
        """
        stack, _ = self._patch_all_stages(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            count_running=Mock(return_value=1),
        )
        with stack:
            result = evolver.run_pipeline()
        statuses = {s.name: s.status for s in result.stages}
        assert statuses["upscale"] == "skipped"
        assert statuses["verify"] == "skipped"
        assert not result.has_errors

    def test_duration_seconds_is_positive(self):
        # duration_seconds is time.monotonic() end-minus-start. On a fast runner
        # an all-mocked pipeline can finish inside the clock's resolution, so the
        # real clock reads the same value twice and the span is 0.0 -- a genuine
        # flake, not a bug in the code. Drive the clock so it advances on every
        # read, making the measured span deterministically positive.
        ticks = itertools.count(start=1.0, step=1.0)
        stack, _ = self._patch_all_stages()
        with stack, patch("evolver.time.monotonic", lambda: next(ticks)):
            result = evolver.run_pipeline()
        assert result.duration_seconds > 0.0

    def test_on_stage_progress_forwarded_to_upscale(self):
        """When on_stage_progress is provided, upscale.run receives on_progress."""
        on_progress = Mock()
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
        )
        with stack:
            evolver.run_pipeline(on_stage_progress=on_progress)
        # upscale.run should have been called with on_progress kwarg
        call_kwargs = mocks["upscale_run"].call_args.kwargs
        assert "on_progress" in call_kwargs
        assert call_kwargs["on_progress"] is not None

    def test_on_stage_progress_not_passed_when_none(self):
        """When on_stage_progress is None, upscale.run does not receive on_progress."""
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
        )
        with stack:
            evolver.run_pipeline(on_stage_progress=None)
        call_kwargs = mocks["upscale_run"].call_args.kwargs
        assert "on_progress" not in call_kwargs

    def test_on_stage_progress_callback_binds_stage_name(self):
        """The on_progress closure passed to upscale.run calls on_stage_progress with stage name."""
        progress_calls = []

        def capture_upscale_run(**kwargs):
            # Simulate upscale calling on_progress
            cb = kwargs.get("on_progress")
            if cb:
                cb(1, 5)
                cb(2, 5)
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
    """The watchdog's stop request: honored between stages, never mid-stage."""

    def test_stops_between_stages_once_asked(self):
        """Asked after whatever ran first, the run ends there.

        Which stage that is belongs to the registry, so the stop is armed by
        the first completion rather than by naming a stage — and the record
        holding exactly one entry is what says the rest were dropped.
        """
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

        assert len(result.stages) == 15


class TestCheckDependenciesWindowSuppression:
    def test_ffprobe_check_passes_create_no_window(self):
        """ffprobe version check must not spawn a visible console window."""
        with patch("evolver.subprocess.run") as mock_run, \
             patch("evolver.config.FFMPEG", Mock(is_file=Mock(return_value=True))):
            mock_run.return_value = Mock(returncode=0)
            evolver.check_dependencies()
            kwargs = mock_run.call_args.kwargs
            assert "creationflags" in kwargs
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


class TestCpuBusySkip:
    """The probe alone decides whether the upscale stage stands down.

    Nothing else exercised `_should_skip_upscale_due_to_cpu`: every pipeline
    test patches it out, so the body it guards two stages with had no cover.
    """

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
