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


if __name__ == "__main__":
    unittest.main()
