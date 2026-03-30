import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import config
import evolver


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
        defaults = {
            "setup_logging": Mock(),
            "check_dependencies": Mock(),
            "sort_run": Mock(return_value=Mock(moved=0, moved_files=[])),
            "purge_run": Mock(return_value=Mock(missing_sorted=[])),
            "scripts_sync_run": Mock(return_value=Mock(ok=True)),
            "bookmarks_sync_run": Mock(return_value=Mock(ok=True)),
            "prompt_scrape_run": Mock(return_value=Mock(ok=True)),
            "upscale_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=0)),
            "has_pending_work": Mock(return_value=False),
            "should_skip_cpu": Mock(return_value=False),
            "duplicate_sizes_run": Mock(return_value=Mock(ok=True)),
            "correspondence_run": Mock(return_value=Mock(ok=True)),
        }
        defaults.update(overrides)
        mocks = defaults

        patch_map = [
            ("evolver.setup_logging", "setup_logging"),
            ("evolver.check_dependencies", "check_dependencies"),
            ("evolver.sort.run", "sort_run"),
            ("evolver.purge_weird.run", "purge_run"),
            ("evolver.scripts_sync.run", "scripts_sync_run"),
            ("evolver.upscale.run", "upscale_run"),
            ("evolver.bookmarks_sync.run", "bookmarks_sync_run"),
            ("evolver.check_correspondence.run", "correspondence_run"),
            ("evolver.check_duplicate_sizes.run", "duplicate_sizes_run"),
            ("evolver.upscale.has_pending_work", "has_pending_work"),
            ("evolver._should_skip_upscale_due_to_cpu", "should_skip_cpu"),
            ("evolver.prompt_scrape.run", "prompt_scrape_run"),
        ]

        with ExitStack() as stack:
            for target, key in patch_map:
                stack.enter_context(patch(target, mocks[key]))
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

    def test_exits_nonzero_on_upscale_deferred_low_disk(self):
        mocks = self._run_pipeline(
            sort_run=Mock(return_value=Mock(moved=1, moved_files=["f"])),
            has_pending_work=Mock(return_value=True),
            upscale_run=Mock(return_value=Mock(failed=0, deferred_low_disk=True, pending_after_run=3)),
        )
        self.assertEqual(mocks["exit_code"], 1)

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
        defaults = {
            "setup_logging": Mock(),
            "check_dependencies": Mock(),
            "sort_run": Mock(return_value=Mock(moved=0, moved_files=[])),
            "purge_run": Mock(return_value=Mock(missing_sorted=[])),
            "scripts_sync_run": Mock(return_value=Mock(ok=True)),
            "bookmarks_sync_run": Mock(return_value=Mock(ok=True)),
            "prompt_scrape_run": Mock(return_value=Mock(ok=True)),
            "upscale_run": Mock(return_value=Mock(failed=0, deferred_low_disk=False, pending_after_run=0)),
            "has_pending_work": Mock(return_value=False),
            "should_skip_cpu": Mock(return_value=False),
            "duplicate_sizes_run": Mock(return_value=Mock(ok=True)),
            "correspondence_run": Mock(return_value=Mock(ok=True)),
        }
        defaults.update(overrides)

        patch_map = [
            ("evolver.sort.run", "sort_run"),
            ("evolver.purge_weird.run", "purge_run"),
            ("evolver.scripts_sync.run", "scripts_sync_run"),
            ("evolver.upscale.run", "upscale_run"),
            ("evolver.bookmarks_sync.run", "bookmarks_sync_run"),
            ("evolver.check_correspondence.run", "correspondence_run"),
            ("evolver.check_duplicate_sizes.run", "duplicate_sizes_run"),
            ("evolver.upscale.has_pending_work", "has_pending_work"),
            ("evolver._should_skip_upscale_due_to_cpu", "should_skip_cpu"),
            ("evolver.prompt_scrape.run", "prompt_scrape_run"),
        ]

        stack = ExitStack()
        for target, key in patch_map:
            stack.enter_context(patch(target, defaults[key]))
        return stack, defaults

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
        self.assertEqual(names, ["purge", "metadata", "sort", "upscale", "verify", "bookmarks", "scripts", "dupes"])

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
        self.assertEqual(started_names, ["purge", "metadata", "sort", "upscale", "verify", "bookmarks", "scripts", "dupes"])

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

    def test_has_errors_true_when_stage_fails(self):
        stack, _ = self._patch_all_stages(
            purge_run=Mock(return_value=Mock(missing_sorted=["file.mp4"])),
        )
        with stack:
            result = evolver.run_pipeline()
        self.assertTrue(result.has_errors)

    def test_duration_seconds_is_positive(self):
        stack, _ = self._patch_all_stages()
        with stack:
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


if __name__ == "__main__":
    unittest.main()
