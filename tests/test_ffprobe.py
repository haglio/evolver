from __future__ import annotations

import subprocess
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from util.ffprobe import (
    duration_seconds,
    frame_rate,
    has_sound,
    orientation_of,
    video_dimensions,
    videoai_tag,
)


def _stand_in_ffprobe_process_answering_by_selector(answers: dict[str, str], calls: list | None = None):
    def popen(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        selector = argv[argv.index("-show_entries") + 1]
        said = answers.get(selector, "") + "\n"
        return SimpleNamespace(communicate=lambda timeout=None: (said, None))
    return popen


def _selectors(calls: list) -> list[str]:
    return [argv[argv.index("-show_entries") + 1] for argv in calls]


class TestFrameRate(unittest.TestCase):
    def test_the_first_video_streams_rate_is_read_exactly(self):
        calls = []
        fake = _stand_in_ffprobe_process_answering_by_selector({"stream=r_frame_rate": "30000/1001"}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert frame_rate(Path("x.mp4")) == Fraction(30000, 1001)
        assert _selectors(calls) == ["stream=r_frame_rate"]
        assert "-select_streams" in calls[0]

    def test_a_rate_ffprobe_cannot_read_is_unknown(self):
        for said in ("", "N/A", "0/0"):
            fake = _stand_in_ffprobe_process_answering_by_selector({"stream=r_frame_rate": said})
            with self.subTest(said=said), patch("util.ffprobe.subprocess.Popen", side_effect=fake):
                assert frame_rate(Path("x.mp4")) is None


class TestDurationSeconds(unittest.TestCase):
    def test_the_containers_duration_is_read_in_seconds(self):
        calls = []
        fake = _stand_in_ffprobe_process_answering_by_selector({"format=duration": "1434.877098"}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert duration_seconds(Path("x.mp4")) == pytest.approx(1434.877098, abs=5e-8)
        assert _selectors(calls) == ["format=duration"]

    def test_a_duration_ffprobe_cannot_read_is_unknown(self):
        fake = _stand_in_ffprobe_process_answering_by_selector({"format=duration": "N/A"})
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert duration_seconds(Path("x.mp4")) is None


class _GivesNoAnswer:

    def __init__(self):
        self.killed = False

    def communicate(self, timeout=None):
        if timeout is None:
            raise AssertionError("waited on ffprobe with no limit")
        raise subprocess.TimeoutExpired("ffprobe", timeout)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        raise AssertionError("waited on an ffprobe that a kill does not end")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.wait()


class TestAProbeGivenNoAnswer(unittest.TestCase):
    def test_it_ends_the_probe_and_answers_unknown_rather_than_wait_on_it(self):
        silent = _GivesNoAnswer()
        with patch("util.ffprobe.subprocess.Popen", return_value=silent):
            assert duration_seconds(Path("cloud/scene one.mp4")) is None
        assert silent.killed


class TestVideoaiTag(unittest.TestCase):
    def test_the_topaz_tag_names_the_models_used(self):
        calls = []
        fake = _stand_in_ffprobe_process_answering_by_selector({"format_tags=videoai": "Enhanced using iris-2"}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert videoai_tag(Path("x.mp4")) == "Enhanced using iris-2"
        assert _selectors(calls) == ["format_tags=videoai"]
        assert "-select_streams" not in calls[0]

    def test_an_untagged_video_reads_as_empty(self):
        fake = _stand_in_ffprobe_process_answering_by_selector({})
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert videoai_tag(Path("x.mp4")) == ""


GEOMETRY = "stream=width,height:stream_tags=rotate"


def _geometry_csv_as_ffprobe_9_writes_it(width, height, rotate=""):
    fields = [width, height] + ([rotate] if rotate else [])
    return ",".join(fields)


class TestFfprobeOrientation(unittest.TestCase):
    def _orientation(self, width, height, rotate="", calls=None):
        fake = _stand_in_ffprobe_process_answering_by_selector({GEOMETRY: _geometry_csv_as_ffprobe_9_writes_it(width, height, rotate)}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            return orientation_of(Path("x.mp4"))

    def test_one_process_answers_width_height_and_rotation(self):
        calls = []
        self._orientation("1920", "1080", calls=calls)

        assert _selectors(calls) == [GEOMETRY]

    def test_an_unreadable_rotate_tag_is_no_rotation_not_no_answer(self):
        assert self._orientation("1920", "1080", rotate="N/A") == "landscape"

    def test_a_wide_clip_is_landscape(self):
        assert self._orientation("1920", "1080") == "landscape"

    def test_a_tall_clip_is_portrait(self):
        assert self._orientation("1080", "1920") == "portrait"

    def test_a_rotated_clip_is_measured_as_the_viewer_sees_it(self):
        assert self._orientation("1920", "1080", rotate="90") == "portrait"

    def test_a_square_clip_counts_as_landscape(self):
        assert self._orientation("1080", "1080") == "landscape"

    def test_a_clip_with_no_dimensions_is_unknown(self):
        assert self._orientation("", "1080") == "unknown"


class TestVideoDimensions(unittest.TestCase):
    def _dimensions(self, width, height, rotate=""):
        fake = _stand_in_ffprobe_process_answering_by_selector({GEOMETRY: _geometry_csv_as_ffprobe_9_writes_it(width, height, rotate)})
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            return video_dimensions(Path("x.mp4"))

    def test_reads_the_streams_stored_width_and_height(self):
        assert self._dimensions("1920", "1080") == (1920, 1080)

    def test_a_rotated_clip_is_measured_as_stored_leaving_the_rotate_tag_to_the_caller(self):
        assert self._dimensions("1920", "1080", rotate="90") == (1920, 1080)

    def test_none_when_a_dimension_is_missing(self):
        assert self._dimensions("", "1080") is None

    def test_none_when_a_dimension_is_not_a_number(self):
        assert self._dimensions("N/A", "1080") is None


class TestHasSound(unittest.TestCase):
    def test_a_file_with_an_audio_stream_has_sound(self):
        calls = []
        fake = _stand_in_ffprobe_process_answering_by_selector({"stream=codec_type": "audio"}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            assert has_sound(Path("x.mp4"))
        assert calls[0][calls[0].index("-select_streams") + 1] == "a"

    def test_a_file_with_no_audio_stream_or_no_answer_has_none(self):
        with patch("util.ffprobe.subprocess.Popen", side_effect=_stand_in_ffprobe_process_answering_by_selector({})):
            assert not has_sound(Path("x.mp4"))
        with patch("util.ffprobe.subprocess.Popen", side_effect=FileNotFoundError("ffprobe")):
            assert not has_sound(Path("x.mp4"))


class TestFfprobeInvocation(unittest.TestCase):
    def test_every_probe_is_framed_for_bare_csv_output(self):
        calls = []
        fake = _stand_in_ffprobe_process_answering_by_selector({"format=duration": "1.0"}, calls)
        with patch("util.ffprobe.subprocess.Popen", side_effect=fake):
            duration_seconds(Path("x.mp4"))
        assert calls[0][:5] == ["ffprobe", "-v", "error", "-of", "csv=p=0"]

    def test_a_missing_ffprobe_is_no_answer_rather_than_a_crash_no_windowless_tool_could_show(self):
        with patch("util.ffprobe.subprocess.Popen",
                   side_effect=FileNotFoundError("ffprobe")):
            assert duration_seconds(Path("x.mp4")) is None
            assert video_dimensions(Path("x.mp4")) is None
            assert orientation_of(Path("x.mp4")) == "unknown"
            assert videoai_tag(Path("x.mp4")) == ""

    def test_an_exit_ffprobe_calls_a_failure_is_the_same_silence_as_no_answer(self):
        def failing(argv, **kwargs):
            return SimpleNamespace(communicate=lambda timeout=None: ("", None), returncode=1)

        with patch("util.ffprobe.subprocess.Popen", side_effect=failing):
            assert duration_seconds(Path("x.mp4")) is None
            assert videoai_tag(Path("x.mp4")) == ""

    def test_ffprobe_never_flashes_a_console_window(self):
        with patch("util.ffprobe.subprocess.Popen") as mock_popen:
            mock_popen.return_value.communicate.return_value = ("1.0\n", None)
            duration_seconds(Path("x.mp4"))
            kwargs = mock_popen.call_args.kwargs
            assert "creationflags" in kwargs
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


if __name__ == "__main__":
    unittest.main()
