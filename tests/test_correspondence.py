import unittest
from pathlib import Path
from unittest.mock import patch

import check_correspondence
import config
from tests.temp_helpers import workspace_temp_dir


class TestCorrespondence(unittest.TestCase):
    def test_run_accepts_outbox_names_as_sorted_plus_topaz(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (sorted_dir / "sourceB" / "portrait" / "clip-b_apo8_gcg5.mp4").write_bytes(b"b")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB" / "clip-b_apo8_gcg5_topaz.mp4").write_bytes(b"b")

            old_sorted = config.SORTED_DIR
            old_outbox = config.OUTBOX_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUTBOX_DIR = outbox_dir
            config.REGEN_ENABLED = False
            try:
                result = check_correspondence.run(show_popup=False)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUTBOX_DIR = old_outbox
                config.REGEN_ENABLED = old_regen_enabled

            self.assertTrue(result.ok)
            self.assertEqual(result.sorted_count, 2)
            self.assertEqual(result.outbox_count, 2)

    def test_run_reports_mismatches_and_can_show_popup(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-b_topaz.mp4").write_bytes(b"b")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-b_topaz_cfr.mp4").write_bytes(b"c")

            old_sorted = config.SORTED_DIR
            old_outbox = config.OUTBOX_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUTBOX_DIR = outbox_dir
            config.REGEN_ENABLED = False
            try:
                with patch("check_correspondence.show_error_window") as show_error_window:
                    result = check_correspondence.run(show_popup=True)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUTBOX_DIR = old_outbox
                config.REGEN_ENABLED = old_regen_enabled

            self.assertFalse(result.ok)
            self.assertEqual(result.sorted_count, 1)
            self.assertEqual(result.outbox_count, 2)
            self.assertEqual(len(result.orphan_outbox), 2)
            self.assertEqual(len(result.orphan_sorted), 1)
            self.assertEqual(result.duplicates, {})
            show_error_window.assert_called_once()

    def test_run_accepts_combined_old_and_regen_outboxes(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"
            regen_outbox_dir = root / "regen_outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)
            (regen_outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (sorted_dir / "sourceB" / "portrait" / "clip-b.mp4").write_bytes(b"b")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (regen_outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB" / "clip-b_topaz.mp4").write_bytes(b"b")

            old_sorted = config.SORTED_DIR
            old_outbox = config.OUTBOX_DIR
            old_regen_outbox = config.REGEN_OUTBOX_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUTBOX_DIR = outbox_dir
            config.REGEN_OUTBOX_DIR = regen_outbox_dir
            config.REGEN_ENABLED = True
            try:
                result = check_correspondence.run(show_popup=False)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUTBOX_DIR = old_outbox
                config.REGEN_OUTBOX_DIR = old_regen_outbox
                config.REGEN_ENABLED = old_regen_enabled

            self.assertTrue(result.ok)
            self.assertEqual(result.sorted_count, 2)
            self.assertEqual(result.outbox_count, 2)

    def test_run_ignores_partial_outbox_files(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a.partial.deadbeef.mp4").write_bytes(b"partial")

            old_sorted = config.SORTED_DIR
            old_outbox = config.OUTBOX_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUTBOX_DIR = outbox_dir
            config.REGEN_ENABLED = False
            try:
                result = check_correspondence.run(show_popup=False)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUTBOX_DIR = old_outbox
                config.REGEN_ENABLED = old_regen_enabled

            self.assertTrue(result.ok)
            self.assertEqual(result.sorted_count, 1)
            self.assertEqual(result.outbox_count, 1)


if __name__ == "__main__":
    unittest.main()
