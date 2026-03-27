import unittest
from unittest.mock import patch

from tasks import purge_weird
from tests.temp_helpers import override_config, workspace_temp_dir


class TestPurgeWeird(unittest.TestCase):
    def test_source_stem_strips_known_processing_suffixes(self):
        cases = [
            ("clip_topaz", "clip"),
            ("clip_topaz_cfr", "clip"),
            ("clip_apo8_gcg5_topaz", "clip_apo8_gcg5"),
            ("clip_apo8_gcg5", "clip"),
            ("clip_apo8_gcg5_Copy(2)", "clip"),
            ("clip_topaz_extra", "clip"),
            ("clip", "clip"),
            ("no_suffix_at_all", "no_suffix_at_all"),
            ("a_b_topaz", "a_b"),
            ("clip_apo8_gcg5_topaz_cfr", "clip_apo8_gcg5"),
        ]
        for stem, expected in cases:
            with self.subTest(stem=stem):
                self.assertEqual(purge_weird.source_stem(stem), expected)

    def test_run_deletes_weird_and_matching_preprocessed_sorted_file(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            sorted_file = sorted_dir / "sourceA" / "landscape" / "clip_apo8_gcg5.mp4"
            sorted_file.parent.mkdir(parents=True)
            sorted_file.write_bytes(b"sorted")
            weird_file = weird_dir / "clip_apo8_gcg5_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 1)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(weird_file.exists())
            self.assertFalse(sorted_file.exists())

    def test_run_deletes_weird_and_matching_sorted_file(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            sorted_file = sorted_dir / "sourceA" / "landscape" / "clip.mp4"
            sorted_file.parent.mkdir(parents=True)
            sorted_file.write_bytes(b"sorted")
            weird_file = weird_dir / "clip_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 1)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(weird_file.exists())
            self.assertFalse(sorted_file.exists())

    def test_run_shows_popup_when_matching_sorted_file_missing(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            weird_file = weird_dir / "missing_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.purge_weird.show_error_window") as show_error_window:
                    result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 0)
            self.assertEqual(result.missing_sorted, ["missing_topaz.mp4"])
            show_error_window.assert_called_once()
            self.assertFalse(weird_file.exists())


if __name__ == "__main__":
    unittest.main()
