import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from util.ffprobe import (
    duration_seconds,
    frame_fingerprint,
    get_orientation,
    video_dimensions,
    videoai_tag,
    _probe,
)


class TestFrameFingerprint(unittest.TestCase):
    @patch("util.ffprobe._probe")
    def test_divides_out_the_rational_frame_rate(self, probe_mock):
        probe_mock.return_value = "30000/1001,40561"
        self.assertEqual(frame_fingerprint(Path("x.mp4")), (29.97002997002997, 40561))

    @patch("util.ffprobe._probe")
    def test_none_when_the_container_counts_no_frames(self, probe_mock):
        probe_mock.return_value = "19001/317,N/A"
        self.assertIsNone(frame_fingerprint(Path("x.mkv")))


class TestDurationSeconds(unittest.TestCase):
    @patch("util.ffprobe._probe_format")
    def test_returns_float_duration(self, probe_mock):
        probe_mock.return_value = "1434.877098"
        self.assertAlmostEqual(duration_seconds(Path("x.mp4")), 1434.877098)

    @patch("util.ffprobe._probe_format")
    def test_none_when_unparseable(self, probe_mock):
        probe_mock.return_value = "N/A"
        self.assertIsNone(duration_seconds(Path("x.mp4")))


class TestVideoaiTag(unittest.TestCase):
    @patch("util.ffprobe._probe_format")
    def test_returns_tag_text(self, probe_mock):
        probe_mock.return_value = "Enhanced using iris-2"
        self.assertEqual(videoai_tag(Path("x.mp4")), "Enhanced using iris-2")
        probe_mock.assert_called_once_with(Path("x.mp4"), "format_tags=videoai")

    @patch("util.ffprobe._probe_format")
    def test_empty_when_untagged(self, probe_mock):
        probe_mock.return_value = ""
        self.assertEqual(videoai_tag(Path("x.mp4")), "")


class TestFfprobeOrientation(unittest.TestCase):
    @patch("util.ffprobe._probe")
    def test_landscape_when_width_greater(self, probe_mock):
        probe_mock.side_effect = ["1920", "1080", ""]
        self.assertEqual(get_orientation(Path("x.mp4")), "landscape")

    @patch("util.ffprobe._probe")
    def test_portrait_when_height_greater(self, probe_mock):
        probe_mock.side_effect = ["1080", "1920", ""]
        self.assertEqual(get_orientation(Path("x.mp4")), "portrait")

    @patch("util.ffprobe._probe")
    def test_rotation_swaps_orientation(self, probe_mock):
        probe_mock.side_effect = ["1920", "1080", "90"]
        self.assertEqual(get_orientation(Path("x.mp4")), "portrait")

    @patch("util.ffprobe._probe")
    def test_unknown_when_missing_dimensions(self, probe_mock):
        probe_mock.side_effect = ["", "1080", ""]
        self.assertEqual(get_orientation(Path("x.mp4")), "unknown")


class TestVideoDimensions(unittest.TestCase):
    @patch("util.ffprobe._probe")
    def test_returns_width_height(self, probe_mock):
        probe_mock.side_effect = ["1920", "1080"]
        self.assertEqual(video_dimensions(Path("x.mp4")), (1920, 1080))

    @patch("util.ffprobe._probe")
    def test_none_when_missing_stream(self, probe_mock):
        probe_mock.side_effect = ["", "1080"]
        self.assertIsNone(video_dimensions(Path("x.mp4")))

    @patch("util.ffprobe._probe")
    def test_none_when_not_integer(self, probe_mock):
        probe_mock.side_effect = ["N/A", "1080"]
        self.assertIsNone(video_dimensions(Path("x.mp4")))


class TestFfprobeWindowSuppression(unittest.TestCase):
    def test_probe_passes_create_no_window(self):
        """ffprobe must not spawn a visible console window on Windows."""
        with patch("util.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = unittest.mock.MagicMock(stdout="1920\n")
            _probe(Path("x.mp4"), "stream=width")
            kwargs = mock_run.call_args.kwargs
            self.assertIn("creationflags", kwargs)
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
