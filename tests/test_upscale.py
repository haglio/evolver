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

    def test_run_deletes_legacy_counterpart_in_regen_mode(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            regen_out_dir = root / "regen" / "upscaled_by_orientation"
            regen_weird_dir = root / "regen" / "kinda_weird"

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
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir
            config.REGEN_ENABLED = True
            config.REGEN_OUT_UPSCALED_DIR = regen_out_dir
            config.REGEN_WEIRD_DIR = regen_weird_dir

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
                config.REGEN_OUT_UPSCALED_DIR = old_regen_out
                config.REGEN_WEIRD_DIR = old_regen_weird

            self.assertEqual(result.processed, 1)
            self.assertFalse(legacy.exists())
            self.assertTrue((regen_out_dir / "portrait" / "sourceA" / "clip_topaz.mp4").exists())


if __name__ == "__main__":
    unittest.main()
