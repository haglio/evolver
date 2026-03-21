import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import evolver


class TestEvolverMain(unittest.TestCase):
    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=False)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_skips_upscale_when_no_pending_work(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=0, moved_files=[])
        purge_run.return_value = Mock(missing_sorted=[])
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 0)
        purge_run.assert_called_once_with()
        upscale_run.assert_not_called()
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=True)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_exits_nonzero_on_correspondence_failure(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=1, moved_files=["new-file"])
        purge_run.return_value = Mock(missing_sorted=[])
        upscale_run.return_value = Mock(failed=0, deferred_low_disk=False)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=False)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        purge_run.assert_called_once_with()
        upscale_run.assert_called_once_with(priority_files=["new-file"], max_items=evolver.config.UPSCALE_BATCH_LIMIT)
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=False)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_exits_nonzero_on_duplicate_size_failure(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=0, moved_files=[])
        purge_run.return_value = Mock(missing_sorted=[])
        duplicate_sizes_run.return_value = Mock(ok=False)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        purge_run.assert_called_once_with()
        upscale_run.assert_not_called()
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=True)
    @patch("evolver.upscale.has_pending_work", return_value=True)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_skips_upscale_when_cpu_busy(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=1, moved_files=["new-file"])
        purge_run.return_value = Mock(missing_sorted=[])
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 0)
        upscale_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
