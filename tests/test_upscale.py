import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
