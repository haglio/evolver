import unittest
from pathlib import Path
from unittest.mock import patch

import check_correspondence
from tests.temp_helpers import override_config, workspace_temp_dir


class TestSortedToOutboxName(unittest.TestCase):
    def test_appends_topaz_before_extension(self):
        cases = [
            (Path("clip.mp4"), "clip_topaz.mp4"),
            (Path("clip_apo8_gcg5.mp4"), "clip_apo8_gcg5_topaz.mp4"),
            (Path("a.mkv"), "a_topaz.mkv"),
        ]
        for sorted_file, expected in cases:
            with self.subTest(sorted_file=sorted_file):
                self.assertEqual(check_correspondence.sorted_to_outbox_name(sorted_file), expected)


class TestCorrespondenceResult(unittest.TestCase):
    def test_ok_requires_matching_counts_and_no_orphans(self):
        result = check_correspondence.CorrespondenceResult(sorted_count=5, outbox_count=5)
        self.assertTrue(result.ok)

    def test_not_ok_on_count_mismatch(self):
        result = check_correspondence.CorrespondenceResult(sorted_count=5, outbox_count=3)
        self.assertFalse(result.ok)

    def test_not_ok_on_orphan_outbox(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=1, outbox_count=1, orphan_outbox=["stray.mp4"],
        )
        self.assertFalse(result.ok)

    def test_not_ok_on_duplicates(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=2, outbox_count=2, duplicates={"clip_topaz.mp4": ["a", "b"]},
        )
        self.assertFalse(result.ok)


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
