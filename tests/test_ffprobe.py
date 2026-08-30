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


GEOMETRY = "stream=width,height:stream_tags=rotate"


def _geometry_csv(width, height, rotate=""):
    """What ffprobe prints for the combined selector.

    The rotate tag is optional, so a clip that has none gets two fields and one
    that has it gets three -- checked against a real ffprobe 9, on an mp4 with
    no tag and an mkv with rotate=90.
    """
    fields = [width, height] + ([rotate] if rotate else [])
    return ",".join(fields)


class TestFfprobeOrientation(unittest.TestCase):
    def _orientation(self, width, height, rotate="", calls=None):
        fake = _ffprobe_answering({GEOMETRY: _geometry_csv(width, height, rotate)}, calls)
        with patch("util.ffprobe.subprocess.run", side_effect=fake):
            return get_orientation(Path("x.mp4"))

    def test_one_process_answers_width_height_and_rotation(self):
        """It was three, and the sort stage calls this once per incoming file --
        so a batch of a hundred clips was three hundred process spawns, and on
        Windows the spawn is the expensive part, not the probing."""
        calls = []
        self._orientation("1920", "1080", calls=calls)

        self.assertEqual(_selectors(calls), [GEOMETRY])

    def test_an_unreadable_rotate_tag_is_no_rotation_not_no_answer(self):
        """The width and height are still good; a tag nothing can parse only
        means the clip is not rotated as far as this can tell."""
        self.assertEqual(self._orientation("1920", "1080", rotate="N/A"), "landscape")

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
        fake = _ffprobe_answering({GEOMETRY: _geometry_csv(width, height)})
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

    def test_a_missing_ffprobe_is_no_answer_rather_than_a_crash(self):
        """Every one of these documents itself as answering None when the probe
        is unavailable, and none of them did: subprocess.run raises
        FileNotFoundError, which escaped all the way out of the backfill tool's
        startup and left it never appearing at all under pythonw."""
        with patch("util.ffprobe.subprocess.run",
                   side_effect=FileNotFoundError("ffprobe")):
            self.assertIsNone(duration_seconds(Path("x.mp4")))
            self.assertIsNone(video_dimensions(Path("x.mp4")))
            self.assertIsNone(frame_fingerprint(Path("x.mp4")))
            self.assertEqual(get_orientation(Path("x.mp4")), "unknown")
            self.assertEqual(videoai_tag(Path("x.mp4")), "")

    def test_ffprobe_never_flashes_a_console_window(self):
        with patch("util.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(stdout="1.0\n")
            duration_seconds(Path("x.mp4"))
            kwargs = mock_run.call_args.kwargs
            self.assertIn("creationflags", kwargs)
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
