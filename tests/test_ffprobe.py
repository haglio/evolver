"""Tests for util.ffprobe, faked at the module's one real boundary.

Thirteen of these used to patch the module-private ``_probe`` helpers with
positional side_effect lists, which pinned the parsing of a string the test
itself supplied and nothing else: the ``-show_entries`` selector each public
function asks ffprobe for, and the argv framing that makes the output
parseable at all, were invisible (audit probes 36-39 corrupted both with the
suite green). The stand-in below answers by selector, the way ffprobe does,
and records the argv so the tests can pin what was asked.
"""

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from util.ffprobe import (
    duration_seconds,
    frame_fingerprint,
    get_orientation,
    video_dimensions,
    videoai_tag,
)


def _ffprobe_answering(answers: dict[str, str], calls: list | None = None):
    """A subprocess.run stand-in that answers by the -show_entries selector."""
    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        selector = argv[argv.index("-show_entries") + 1]
        return SimpleNamespace(stdout=answers.get(selector, "") + "\n")
    return run


def _selectors(calls: list) -> list[str]:
    return [argv[argv.index("-show_entries") + 1] for argv in calls]


class TestFrameFingerprint(unittest.TestCase):
    def test_a_rational_frame_rate_is_divided_out(self):
        calls = []
        fake = _ffprobe_answering({"stream=r_frame_rate,nb_frames": "30000/1001,40561"}, calls)
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertEqual(frame_fingerprint(Path("x.mp4")), (29.97002997002997, 40561))
        self.assertEqual(_selectors(calls), ["stream=r_frame_rate,nb_frames"])
        self.assertIn("-select_streams", calls[0])  # the first video stream's numbers

    def test_a_bare_integer_frame_rate_still_fingerprints(self):
        # Some containers report "30", not "30/1"; the empty denominator must
        # default to 1 rather than raise.
        fake = _ffprobe_answering({"stream=r_frame_rate,nb_frames": "30,100"})
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertEqual(frame_fingerprint(Path("x.mp4")), (30.0, 100))

    def test_a_container_with_no_frame_count_has_no_fingerprint(self):
        fake = _ffprobe_answering({"stream=r_frame_rate,nb_frames": "19001/317,N/A"})
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertIsNone(frame_fingerprint(Path("x.mkv")))


class TestDurationSeconds(unittest.TestCase):
    def test_the_containers_duration_is_read_in_seconds(self):
        calls = []
        fake = _ffprobe_answering({"format=duration": "1434.877098"}, calls)
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertAlmostEqual(duration_seconds(Path("x.mp4")), 1434.877098)
        self.assertEqual(_selectors(calls), ["format=duration"])

    def test_a_duration_ffprobe_cannot_read_is_unknown(self):
        fake = _ffprobe_answering({"format=duration": "N/A"})
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertIsNone(duration_seconds(Path("x.mp4")))


class TestVideoaiTag(unittest.TestCase):
    def test_the_topaz_tag_names_the_models_used(self):
        calls = []
        fake = _ffprobe_answering({"format_tags=videoai": "Enhanced using iris-2"}, calls)
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertEqual(videoai_tag(Path("x.mp4")), "Enhanced using iris-2")
        self.assertEqual(_selectors(calls), ["format_tags=videoai"])
        self.assertNotIn("-select_streams", calls[0])  # a format probe, not a stream one

    def test_an_untagged_video_reads_as_empty(self):
        fake = _ffprobe_answering({})
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            self.assertEqual(videoai_tag(Path("x.mp4")), "")


class TestFfprobeOrientation(unittest.TestCase):
    def _orientation(self, width, height, rotate=""):
        fake = _ffprobe_answering({
            "stream=width": width,
            "stream=height": height,
            "stream_tags=rotate": rotate,
        })
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            return get_orientation(Path("x.mp4"))

    def test_a_wide_clip_is_landscape(self):
        self.assertEqual(self._orientation("1920", "1080"), "landscape")

    def test_a_tall_clip_is_portrait(self):
        self.assertEqual(self._orientation("1080", "1920"), "portrait")

    def test_a_rotated_clip_is_measured_as_the_viewer_sees_it(self):
        self.assertEqual(self._orientation("1920", "1080", rotate="90"), "portrait")

    def test_a_square_clip_counts_as_landscape(self):
        # The tie-break: it decides which sorted folder a square video lands
        # in, and flipping it to portrait used to change nothing (audit
        # probe 16).
        self.assertEqual(self._orientation("1080", "1080"), "landscape")

    def test_a_clip_with_no_dimensions_is_unknown(self):
        self.assertEqual(self._orientation("", "1080"), "unknown")


class TestVideoDimensions(unittest.TestCase):
    def _dimensions(self, width, height):
        fake = _ffprobe_answering({"stream=width": width, "stream=height": height})
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            return video_dimensions(Path("x.mp4"))

    def test_reads_the_streams_stored_width_and_height(self):
        self.assertEqual(self._dimensions("1920", "1080"), (1920, 1080))

    def test_none_when_a_dimension_is_missing(self):
        self.assertIsNone(self._dimensions("", "1080"))

    def test_none_when_a_dimension_is_not_a_number(self):
        self.assertIsNone(self._dimensions("N/A", "1080"))


class TestFfprobeInvocation(unittest.TestCase):
    def test_every_probe_is_framed_for_bare_csv_output(self):
        """The -of csv=p=0 framing is what frame_fingerprint's split(',')
        parses; dropping it used to leave every test green (audit probe 38)."""
        calls = []
        fake = _ffprobe_answering({"format=duration": "1.0"}, calls)
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            duration_seconds(Path("x.mp4"))
        self.assertEqual(calls[0][:5], ["ffprobe", "-v", "error", "-of", "csv=p=0"])

    def test_ffprobe_never_flashes_a_console_window(self):
        with patch("util.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(stdout="1.0\n")
            duration_seconds(Path("x.mp4"))
            kwargs = mock_run.call_args.kwargs
            self.assertIn("creationflags", kwargs)
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
