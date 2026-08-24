import itertools
import subprocess
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import config
import evolver


def _stage_mocks() -> dict:
    """A stand-in for every stage the pipeline calls.

    One list, used by both helpers below, so a newly added stage is stubbed
    everywhere at once. A stage left off it runs for real against the live
    library and the sibling apps' saved state, which turns a unit test into a
    maintenance run.
    """
    return {
        "sort_run": Mock(return_value=Mock(moved=0, moved_files=[])),
        "purge_run": Mock(return_value=Mock(missing_sorted=[])),
        "scripts_sync_run": Mock(return_value=Mock(ok=True)),
        "bookmarks_sync_run": Mock(return_value=Mock(ok=True)),
        "prompt_scrape_run": Mock(return_value=Mock(ok=True)),
        "upscale_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=0)),
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
    ("evolver.sort.run", "sort_run"),
    ("evolver.purge_weird.run", "purge_run"),
    ("evolver.clip_scripts.run", "clip_scripts_run"),
    ("evolver.scene_scripts.run", "scene_scripts_run"),
    ("evolver.scripts_sync.run", "scripts_sync_run"),
    ("evolver.upscale.run", "upscale_run"),
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


class TestEvolverMain(unittest.TestCase):
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
            with self.assertRaises(SystemExit) as exc:
                evolver.main()

        mocks["exit_code"] = exc.exception.code
        return mocks

    # --- Dependency check ---

    def test_exits_nonzero_on_dependency_check_failure(self):
        mocks = self._run_pipeline(
            check_dependencies=Mock(side_effect=RuntimeError("ffprobe not found")),
        )
        self.assertEqual(mocks["exit_code"], 1)
        mocks["sort_run"].assert_not_called()

    def test_exits_nonzero_on_purge_missing_sorted(self):
        mocks = self._run_pipeline(
            purge_run=Mock(return_value=Mock(missing_sorted=["file.mp4"])),
        )
        self.assertEqual(mocks["exit_code"], 1)

    # --- Stage sequencing ---

    def test_skips_upscale_when_no_pending_work(self):
        mocks = self._run_pipeline()
        self.assertEqual(mocks["exit_code"], 0)
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_called_once_with(show_popup=True)

    def test_skips_correspondence_when_upscale_has_pending(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=3, moved_files=["a", "b", "c"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=1)),
        )
        self.assertEqual(mocks["exit_code"], 0)
        mocks["upscale_run"].assert_called_once()
        mocks["correspondence_run"].assert_not_called()

    def test_skips_upscale_and_correspondence_when_cpu_busy(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
            has_pending_work=Mock(return_value=True),
            should_skip_cpu=Mock(return_value=True),
        )
        self.assertEqual(mocks["exit_code"], 0)
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_not_called()

    def test_runs_upscale_with_priority_files(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
            has_pending_work=Mock(return_value=True),
        )
        self.assertEqual(mocks["exit_code"], 0)
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
        self.assertEqual(mocks["exit_code"], 0)
        mocks["upscale_run"].assert_not_called()
        mocks["correspondence_run"].assert_not_called()

    def test_cli_run_neither_starts_nor_stops_nor_manages_nonai_encodes(self):
        mocks = self._run_pipeline()
        mocks["nonai_run"].assert_called_once_with(
            allow_start=False, stop=False, presence_managed=False)

    def test_exits_nonzero_on_nonai_upscale_failure(self):
        mocks = self._run_pipeline(
            nonai_run=Mock(return_value=Mock(failed=1, deferred_low_disk=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    # --- Exit code propagation ---

    def test_exits_nonzero_on_correspondence_failure(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["new-file"])),
            has_pending_work=Mock(return_value=True),
            correspondence_run=Mock(return_value=Mock(ok=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    def test_exits_nonzero_on_duplicate_size_failure(self):
        mocks = self._run_pipeline(
            duplicate_sizes_run=Mock(return_value=Mock(ok=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    def test_exits_nonzero_on_scripts_sync_failure(self):
        mocks = self._run_pipeline(
            scripts_sync_run=Mock(return_value=Mock(ok=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    def test_exits_nonzero_on_bookmarks_sync_failure(self):
        mocks = self._run_pipeline(
            bookmarks_sync_run=Mock(return_value=Mock(ok=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    def test_exits_nonzero_on_upscale_failure(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=2, deferred_low_disk=False, pending_after_run=0)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    def test_exits_zero_when_upscale_only_held_back_for_low_disk(self):
        """A hold is not a failure: nothing broke, there is just no room yet."""
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=True, pending_after_run=3)),
        )
        self.assertEqual(mocks["exit_code"], 0)

    def test_exits_nonzero_on_prompt_scrape_failure(self):
        mocks = self._run_pipeline(
            prompt_scrape_run=Mock(return_value=Mock(ok=False)),
        )
        self.assertEqual(mocks["exit_code"], 1)

    # --- All stages called on clean run ---

    def test_all_stages_called_on_clean_run_with_pending_work(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
        )
        self.assertEqual(mocks["exit_code"], 0)
        mocks["sort_run"].assert_called_once()
        mocks["purge_run"].assert_called_once()
        mocks["clip_scripts_run"].assert_called_once()
        mocks["scripts_sync_run"].assert_called_once_with(show_popup=True)
        mocks["bookmarks_sync_run"].assert_called_once()
        mocks["prompt_scrape_run"].assert_called_once()
        mocks["upscale_run"].assert_called_once()
        mocks["duplicate_sizes_run"].assert_called_once_with(show_popup=True)
        mocks["correspondence_run"].assert_called_once_with(show_popup=True)


class TestRunPipeline(unittest.TestCase):
    """Tests for evolver.run_pipeline() and its callback protocol."""

    def _patch_all_stages(self, **overrides):
        """Return an ExitStack context that patches all stages for run_pipeline()."""
        defaults = _stage_mocks()
        defaults.update(overrides)
        return _patched_stages(defaults), defaults

    def test_returns_pipeline_result(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        self.assertIsInstance(result, evolver.PipelineResult)
        self.assertFalse(result.has_errors)
        self.assertGreater(len(result.stages), 0)

    def test_stage_records_have_correct_names(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        self.assertEqual(names, ["purge", "metadata", "sort", "upscale", "genau_deliver", "upscale_non_ai", "verify", "references", "bookmarks", "clip_scripts", "scene_scripts", "scripts", "group_non_ai", "dupes"])

    def test_references_run_before_bookmarks_prunes_the_favorites(self):
        """Both stages touch favs.csv, and bookmarks drops rows whose file is gone.

        Repointing has to come first, or a favorite whose video merely moved is
        deleted on the very run that could have saved it.
        """
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        names = [s.name for s in result.stages]
        self.assertLess(names.index("references"), names.index("bookmarks"))

    def test_skipped_stages_have_skip_status(self):
        stack, _ = self._patch_all_stages()
        with stack:
            result = evolver.run_pipeline()
        upscale_stage = next(s for s in result.stages if s.name == "upscale")
        self.assertEqual(upscale_stage.status, "skipped")
        self.assertEqual(upscale_stage.skip_reason, "no_pending_work")

    def test_on_stage_start_called_for_each_stage(self):
        on_start = Mock()
        stack, _ = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_start=on_start)
        started_names = [call.args[0] for call in on_start.call_args_list]
        self.assertEqual(started_names, ["purge", "metadata", "sort", "upscale", "genau_deliver", "upscale_non_ai", "verify", "references", "bookmarks", "clip_scripts", "scene_scripts", "scripts", "group_non_ai", "dupes"])

    def test_on_stage_complete_called_with_result_and_status(self):
        on_complete = Mock()
        stack, mocks = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_complete=on_complete)
        # Check purge stage callback (first stage)
        purge_call = on_complete.call_args_list[0]
        self.assertEqual(purge_call.args[0], "purge")
        self.assertEqual(purge_call.args[1], mocks["purge_run"].return_value)
        self.assertIsInstance(purge_call.args[2], float)  # elapsed
        self.assertEqual(purge_call.args[3], "completed")

    def test_on_stage_complete_reports_skipped_for_upscale(self):
        on_complete = Mock()
        stack, _ = self._patch_all_stages()
        with stack:
            evolver.run_pipeline(on_stage_complete=on_complete)
        upscale_call = next(c for c in on_complete.call_args_list if c.args[0] == "upscale")
        self.assertIsNone(upscale_call.args[1])  # no result
        self.assertEqual(upscale_call.args[3], "skipped")

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
        self.assertTrue(result.has_errors)

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
        self.assertEqual(errored, ["purge"])

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
        self.assertEqual(statuses["upscale_non_ai"], "warning")
        self.assertFalse(result.has_errors)

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
        self.assertEqual(statuses["upscale_non_ai"], "error")

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
        self.assertEqual(statuses["upscale"], "skipped")
        self.assertEqual(statuses["verify"], "skipped")
        self.assertFalse(result.has_errors)

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
        self.assertGreater(result.duration_seconds, 0.0)

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
        self.assertIn("on_progress", call_kwargs)
        self.assertIsNotNone(call_kwargs["on_progress"])

    def test_on_stage_progress_not_passed_when_none(self):
        """When on_stage_progress is None, upscale.run does not receive on_progress."""
        stack, mocks = self._patch_all_stages(
            has_pending_work=Mock(return_value=True),
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
        )
        with stack:
            evolver.run_pipeline(on_stage_progress=None)
        call_kwargs = mocks["upscale_run"].call_args.kwargs
        self.assertNotIn("on_progress", call_kwargs)

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
        self.assertEqual(progress_calls, [("upscale", 1, 5), ("upscale", 2, 5)])


class TestCooperativeStop(unittest.TestCase):
    """The watchdog's stop request: honored between stages, never mid-stage."""

    def test_stops_between_stages_once_asked(self):
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline(should_stop=lambda: mocks["purge_run"].called)

        self.assertEqual([s.name for s in result.stages], ["purge"])
        mocks["prompt_scrape_run"].assert_not_called()
        mocks["sort_run"].assert_not_called()

    def test_a_stop_that_is_never_requested_changes_nothing(self):
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline(should_stop=lambda: False)

        self.assertEqual(len(result.stages), 14)


class TestCheckDependenciesWindowSuppression(unittest.TestCase):
    def test_ffprobe_check_passes_create_no_window(self):
        """ffprobe version check must not spawn a visible console window."""
        with patch("evolver.subprocess.run") as mock_run, \
             patch("evolver.config.FFMPEG", Mock(is_file=Mock(return_value=True))):
            mock_run.return_value = Mock(returncode=0)
            evolver.check_dependencies()
            kwargs = mock_run.call_args.kwargs
            self.assertIn("creationflags", kwargs)
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
