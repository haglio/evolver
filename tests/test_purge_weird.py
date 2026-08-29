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

    def test_run_deletes_orphaned_metadata_json(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            metadata_dir = root / "metadata"
            weird_dir.mkdir(parents=True)
            weird_file = weird_dir / "clip_topaz.mp4"
            weird_file.write_bytes(b"weird")
            # Metadata JSON lives under a different subpath than kinda_weird,
            # mirroring where the file was scraped before it was moved to weird.
            json_file = metadata_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "clip_topaz.json"
            json_file.parent.mkdir(parents=True)
            json_file.write_text('{"video":{"prompt":"test"}}', encoding="utf-8")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir, METADATA_DIR=metadata_dir):
                with patch("tasks.purge_weird.show_error_window"):
                    result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_metadata, 1)
            self.assertFalse(json_file.exists())

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

    def test_run_deletes_every_sorted_copy_matching_the_source_name(self):
        """Pinned as it behaves today: one weird file whose source basename
        lives under two source folders loses BOTH copies -- rglob matches by
        name alone, and every match is unlinked (audit probe P13 narrowed the
        loop to one match with the suite unchanged). Whether deleting both is
        the intended behaviour is recorded in the changelog as a question,
        not answered here."""
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            copy_a = sorted_dir / "sourceA" / "landscape" / "clip.mp4"
            copy_b = sorted_dir / "sourceB" / "portrait" / "clip.mp4"
            for copy in (copy_a, copy_b):
                copy.parent.mkdir(parents=True)
                copy.write_bytes(b"sorted")
            (weird_dir / "clip_topaz.mp4").write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_sorted, 2)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(copy_a.exists())
            self.assertFalse(copy_b.exists())


if __name__ == "__main__":
    unittest.main()
