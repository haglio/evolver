import unittest
from unittest.mock import patch

import check_correspondence
from tests.temp_helpers import override_config, workspace_temp_dir


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

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                result = check_correspondence.run(show_popup=False)

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

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                with patch("check_correspondence.show_error_window") as show_error_window:
                    result = check_correspondence.run(show_popup=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.sorted_count, 1)
            self.assertEqual(result.outbox_count, 2)
            self.assertEqual(len(result.orphan_outbox), 2)
            self.assertEqual(len(result.orphan_sorted), 1)
            self.assertEqual(result.duplicates, {})
            show_error_window.assert_called_once()

    def test_run_ignores_partial_outbox_files(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a.partial.deadbeef.mp4").write_bytes(b"partial")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                result = check_correspondence.run(show_popup=False)

            self.assertTrue(result.ok)
            self.assertEqual(result.sorted_count, 1)
            self.assertEqual(result.outbox_count, 1)


if __name__ == "__main__":
    unittest.main()
