import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from tasks import upscale


class TestUpscaleHelpers(unittest.TestCase):
    def test_already_processed_checks_all_locations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            weird = root / "weird"
            (out / "landscape" / "provider").mkdir(parents=True)
            (out / "portrait" / "provider").mkdir(parents=True)
            weird.mkdir(parents=True)

            old_out = config.OUT_UPSCALED_DIR
            old_weird = config.WEIRD_DIR
            config.OUT_UPSCALED_DIR = out
            config.WEIRD_DIR = weird
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

    def test_run_processes_dynamic_source_and_creates_out_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
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
            config.SORTED_DIR = sorted_dir
            config.OUT_UPSCALED_DIR = out_dir
            config.WEIRD_DIR = weird_dir

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            try:
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg):
                    result = upscale.run()

                self.assertEqual(result.processed, 1)
                self.assertEqual(result.failed, 0)
                self.assertTrue((out_dir / "landscape" / source).is_dir())
                self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())
            finally:
                config.SORTED_DIR = old_sorted
                config.OUT_UPSCALED_DIR = old_out
                config.WEIRD_DIR = old_weird


if __name__ == "__main__":
    unittest.main()
