import unittest
from pathlib import Path

import config
from util import topaz


class TestCommand(unittest.TestCase):
    def test_builds_silent_video_command(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), "the-filter", "the-tag")
        self.assertEqual(cmd[0], str(config.FFMPEG))
        self.assertIn("in.mp4", cmd)
        self.assertIn("the-filter", cmd)
        self.assertIn("videoai=the-tag", cmd)
        self.assertIn("-an", cmd)
        self.assertEqual(cmd[-1], "tmp.mp4")

    def test_keep_audio_reencodes_instead_of_stripping(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), "f", "t", keep_audio=True)
        self.assertNotIn("-an", cmd)
        self.assertIn("aac", cmd)


class TestEnvironment(unittest.TestCase):
    def test_points_topaz_at_the_model_directory(self):
        env = topaz.environment()
        self.assertEqual(env["TVAI_MODEL_DIR"], str(config.TVAI_MODEL_DIR))
        self.assertEqual(env["TVAI_MODEL_DATA_DIR"], str(config.TVAI_MODEL_DIR))


if __name__ == "__main__":
    unittest.main()
