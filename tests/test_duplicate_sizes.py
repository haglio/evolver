import unittest
from pathlib import Path
from unittest.mock import patch

import check_duplicate_sizes
import config
from tests.temp_helpers import workspace_temp_dir


class TestDuplicateSizes(unittest.TestCase):
    def test_run_is_ok_when_all_files_have_unique_sizes(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (sorted_dir / "sourceB" / "portrait" / "clip-b.mp4").write_bytes(b"bb")

            old_non_ai = config.NON_AI_DIR
            config.NON_AI_DIR = sorted_dir
            try:
                result = check_duplicate_sizes.run(show_popup=False)
            finally:
                config.NON_AI_DIR = old_non_ai

            self.assertTrue(result.ok)
            self.assertEqual(result.scanned_count, 2)
            self.assertEqual(result.duplicate_groups, {})

    def test_run_reports_exact_size_duplicates_and_can_show_popup(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"same-size")
            (sorted_dir / "sourceB" / "portrait" / "clip-b.mp4").write_bytes(b"same-size")
            (sorted_dir / "sourceB" / "portrait" / "clip-c.mp4").write_bytes(b"different-size")

            old_non_ai = config.NON_AI_DIR
            config.NON_AI_DIR = sorted_dir
            try:
                with patch("check_duplicate_sizes.show_error_window") as show_error_window:
                    result = check_duplicate_sizes.run(show_popup=True)
            finally:
                config.NON_AI_DIR = old_non_ai

            self.assertFalse(result.ok)
            self.assertEqual(result.scanned_count, 3)
            self.assertEqual(len(result.duplicate_groups), 1)
            self.assertEqual(
                next(iter(result.duplicate_groups.values())),
                [
                    "sourceA\\landscape\\clip-a.mp4",
                    "sourceB\\portrait\\clip-b.mp4",
                ],
            )
            show_error_window.assert_called_once()
