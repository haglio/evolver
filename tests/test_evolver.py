import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import evolver


class TestEvolverMain(unittest.TestCase):
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_skips_upscale_when_sort_moved_zero(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
    ):
        sort_run.return_value = Mock(moved=0)
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
    ):
        sort_run.return_value = Mock(moved=1)
        purge_run.return_value = Mock(missing_sorted=[])
        upscale_run.return_value = Mock(failed=0)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=False)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        purge_run.assert_called_once_with()
        upscale_run.assert_called_once_with()
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

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
    ):
        sort_run.return_value = Mock(moved=0)
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


if __name__ == "__main__":
    unittest.main()
