import unittest
from unittest.mock import patch

from util.ffprobe import get_orientation


class TestFfprobeOrientation(unittest.TestCase):
    @patch("util.ffprobe._probe")
    def test_landscape_when_width_greater(self, probe_mock):
        probe_mock.side_effect = ["1920", "1080", ""]
        self.assertEqual(get_orientation(__import__("pathlib").Path("x.mp4")), "landscape")

    @patch("util.ffprobe._probe")
    def test_portrait_when_height_greater(self, probe_mock):
        probe_mock.side_effect = ["1080", "1920", ""]
        self.assertEqual(get_orientation(__import__("pathlib").Path("x.mp4")), "portrait")

    @patch("util.ffprobe._probe")
    def test_rotation_swaps_orientation(self, probe_mock):
        probe_mock.side_effect = ["1920", "1080", "90"]
        self.assertEqual(get_orientation(__import__("pathlib").Path("x.mp4")), "portrait")

    @patch("util.ffprobe._probe")
    def test_unknown_when_missing_dimensions(self, probe_mock):
        probe_mock.side_effect = ["", "1080", ""]
        self.assertEqual(get_orientation(__import__("pathlib").Path("x.mp4")), "unknown")


if __name__ == "__main__":
    unittest.main()
