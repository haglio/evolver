import unittest
from pathlib import Path
from unittest.mock import patch

import config
from tasks import upscale
from tests.temp_helpers import workspace_temp_dir


class TestUpscaleHelpers(unittest.TestCase):
    def test_already_processed_checks_all_locations(self):
        with workspace_temp_dir() as root:
            out = root / "out"
            weird = root / "weird"
            (out / "landscape" / "provider").mkdir(parents=True)
            (out / "portrait" / "provider").mkdir(parents=True)
            weird.mkdir(parents=True)

            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.OUT_UPSCALED_DIR = out
            config.WEIRD_DIR = weird
            config.REGEN_ENABLED = False
            try:
                self.assertFalse(upscale._already_processed("provider", "a_topaz.mp4"))

                p1 = out / "landscape" / "provider" / "a_topaz.mp4"
                p1.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4"))

                p1.unlink()
                p2 = weird / "a_topaz.mp4"
                p2.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4"))
            finally:
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled

    def test_run_processes_dynamic_source_and_creates_out_dir(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            source = "brandnew"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = False

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            try:
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

                self.assertEqual(result.processed, 1)
                self.assertEqual(result.failed, 0)
                self.assertTrue((out_dir / "landscape" / source).is_dir())
                self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled

    def test_collect_candidates_prioritizes_newly_sorted_files(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"

            priority = sorted_dir / "sourceB" / "portrait" / "priority.mp4"
            backlog = sorted_dir / "sourceA" / "landscape" / "backlog.mp4"
            priority.parent.mkdir(parents=True)
            backlog.parent.mkdir(parents=True)
            priority.write_bytes(b"video")
            backlog.write_bytes(b"video")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = False
            try:
                candidates = upscale.collect_candidates(priority_files=[priority])
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled

            self.assertEqual(candidates[0][0], priority)
            self.assertEqual(candidates[1][0], backlog)

    def test_run_removes_stale_partial_outputs_before_processing(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            source = "provider2"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            stale_partial = out_dir / "landscape" / source / "clip.partial.deadbeef.mp4"
            stale_partial.parent.mkdir(parents=True)
            stale_partial.write_bytes(b"partial")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = False

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            try:
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled

            self.assertEqual(result.processed, 1)
            self.assertFalse(stale_partial.exists())
            self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())

    def test_run_deletes_legacy_counterpart_in_regen_mode(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_out_dir = root / "regen" / "upscaled_by_orientation"
            regen_weird_dir = root / "regen" / "kinda_weird"
            regen_skip_file = root / ".regen-skip.txt"

            in_file = sorted_dir / "sourceA" / "portrait" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")
            legacy = out_dir / "portrait" / "sourceA" / "clip_topaz.mp4"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            old_regen_out = config.REGEN_OUT_UPSCALED_DIR
            old_regen_weird = config.REGEN_WEIRD_DIR
            old_regen_skip = config.REGEN_SKIP_FILE
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_OUT_UPSCALED_DIR = regen_out_dir
            config.REGEN_WEIRD_DIR = regen_weird_dir
            config.REGEN_SKIP_FILE = regen_skip_file

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            try:
                with patch("tasks.upscale._has_current_upscale_standard", return_value=False), \
                     patch("tasks.upscale._source_is_preprocessed_and_matches_legacy", return_value=False), \
                     patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled
                config.REGEN_OUT_UPSCALED_DIR = old_regen_out
                config.REGEN_WEIRD_DIR = old_regen_weird
                config.REGEN_SKIP_FILE = old_regen_skip

            self.assertEqual(result.processed, 1)
            self.assertFalse(legacy.exists())
            self.assertTrue((regen_out_dir / "portrait" / "sourceA" / "clip_topaz.mp4").exists())

    def test_collect_candidates_skips_regen_manifest_entries(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_skip_file = root / ".regen-skip.txt"

            skipped_file = sorted_dir / "sourceA" / "landscape" / "skip-me.mp4"
            normal_file = sorted_dir / "sourceA" / "landscape" / "keep-me.mp4"
            skipped_file.parent.mkdir(parents=True)
            skipped_file.write_bytes(b"video")
            normal_file.write_bytes(b"video")
            regen_skip_file.write_text("sourceA/landscape/skip-me.mp4\n", encoding="utf-8")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            old_regen_skip = config.REGEN_SKIP_FILE
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_SKIP_FILE = regen_skip_file
            try:
                candidates = upscale.collect_candidates()
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled
                config.REGEN_SKIP_FILE = old_regen_skip

            self.assertEqual([candidate[0].name for candidate in candidates], ["keep-me.mp4"])

    def test_run_copies_current_standard_legacy_file_in_regen_mode(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_out_dir = root / "regen" / "upscaled_by_orientation"
            regen_weird_dir = root / "regen" / "kinda_weird"
            regen_skip_file = root / ".regen-skip.txt"

            in_file = sorted_dir / "sourceA" / "portrait" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")
            legacy = out_dir / "portrait" / "sourceA" / "clip_topaz.mp4"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-current")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            old_regen_out = config.REGEN_OUT_UPSCALED_DIR
            old_regen_weird = config.REGEN_WEIRD_DIR
            old_regen_skip = config.REGEN_SKIP_FILE
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_OUT_UPSCALED_DIR = regen_out_dir
            config.REGEN_WEIRD_DIR = regen_weird_dir
            config.REGEN_SKIP_FILE = regen_skip_file

            try:
                with patch("tasks.upscale._has_current_upscale_standard", return_value=True), \
                     patch("tasks.upscale._run_ffmpeg") as run_ffmpeg, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled
                config.REGEN_OUT_UPSCALED_DIR = old_regen_out
                config.REGEN_WEIRD_DIR = old_regen_weird
                config.REGEN_SKIP_FILE = old_regen_skip

            self.assertEqual(result.copied_from_legacy, 1)
            run_ffmpeg.assert_not_called()
            self.assertFalse(legacy.exists())
            self.assertEqual((regen_out_dir / "portrait" / "sourceA" / "clip_topaz.mp4").read_bytes(), b"legacy-current")

    def test_run_records_regen_skip_after_failed_legacy_backed_item(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_out_dir = root / "regen" / "upscaled_by_orientation"
            regen_weird_dir = root / "regen" / "kinda_weird"
            regen_skip_file = root / ".regen-skip.txt"

            in_file = sorted_dir / "sourceA" / "portrait" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")
            legacy = out_dir / "portrait" / "sourceA" / "clip_topaz.mp4"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            old_regen_out = config.REGEN_OUT_UPSCALED_DIR
            old_regen_weird = config.REGEN_WEIRD_DIR
            old_regen_skip = config.REGEN_SKIP_FILE
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_OUT_UPSCALED_DIR = regen_out_dir
            config.REGEN_WEIRD_DIR = regen_weird_dir
            config.REGEN_SKIP_FILE = regen_skip_file

            try:
                with patch("tasks.upscale._run_ffmpeg", return_value=False), \
                     patch("tasks.upscale._has_current_upscale_standard", return_value=False), \
                     patch("tasks.upscale._source_is_preprocessed_and_matches_legacy", return_value=False), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled
                config.REGEN_OUT_UPSCALED_DIR = old_regen_out
                config.REGEN_WEIRD_DIR = old_regen_weird
                config.REGEN_SKIP_FILE = old_regen_skip

            self.assertEqual(result.failed, 1)
            self.assertTrue(regen_skip_file.exists())
            self.assertIn("sourceA/portrait/clip.mp4", regen_skip_file.read_text(encoding="utf-8"))

    def test_run_copies_matching_preprocessed_legacy_file_in_regen_mode(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_out_dir = root / "regen" / "upscaled_by_orientation"
            regen_weird_dir = root / "regen" / "kinda_weird"
            regen_skip_file = root / ".regen-skip.txt"

            in_file = sorted_dir / "sourceA" / "landscape" / "clip_apo8_gcg5.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"preprocessed-source")
            legacy = out_dir / "landscape" / "sourceA" / "clip_apo8_gcg5_topaz.mp4"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-preprocessed")

            old_sorted = config.SORTED_DIR
            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            old_regen_enabled = config.REGEN_ENABLED
            old_regen_out = config.REGEN_OUT_UPSCALED_DIR
            old_regen_weird = config.REGEN_WEIRD_DIR
            old_regen_skip = config.REGEN_SKIP_FILE
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_OUT_UPSCALED_DIR = regen_out_dir
            config.REGEN_WEIRD_DIR = regen_weird_dir
            config.REGEN_SKIP_FILE = regen_skip_file

            try:
                with patch("tasks.upscale._has_current_upscale_standard", return_value=False), \
                     patch("tasks.upscale._source_is_preprocessed_and_matches_legacy", return_value=True), \
                     patch("tasks.upscale._run_ffmpeg") as run_ffmpeg, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird
                config.REGEN_ENABLED = old_regen_enabled
                config.REGEN_OUT_UPSCALED_DIR = old_regen_out
                config.REGEN_WEIRD_DIR = old_regen_weird
                config.REGEN_SKIP_FILE = old_regen_skip

            self.assertEqual(result.copied_from_legacy, 1)
            run_ffmpeg.assert_not_called()
            self.assertFalse(legacy.exists())
            self.assertEqual((regen_out_dir / "landscape" / "sourceA" / "clip_apo8_gcg5_topaz.mp4").read_bytes(), b"legacy-preprocessed")


if __name__ == "__main__":
    unittest.main()
