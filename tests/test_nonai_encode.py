from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import nonai_encode
from tests.temp_helpers import workspace_temp_dir
from util import nonai_job


class TestParseTopazArguments(unittest.TestCase):
    def test_reads_the_input_and_the_output_through_the_spaces_library_folder_names_hold(self):
        source, out = nonai_encode._parse_topaz_arguments((
            "ffmpeg.exe", "-i", "C:/lib/0 unsorted/scene one.mp4", "-vf", "x",
            "C:/lib/3 done/scene one.partial.ab12.mp4"))

        assert source == Path("C:/lib/0 unsorted/scene one.mp4")
        assert out == Path("C:/lib/3 done/scene one.partial.ab12.mp4")

    def test_arguments_with_no_input_name_neither(self):
        assert nonai_encode._parse_topaz_arguments(("ffmpeg.exe", "-version")) == (None, None)

    def test_an_input_flag_with_nothing_after_it_names_neither(self):
        assert nonai_encode._parse_topaz_arguments(("ffmpeg.exe", "-i")) == (None, None)

    def test_no_arguments_name_neither(self):
        assert nonai_encode._parse_topaz_arguments(()) == (None, None)


class TestPercentEncoded(unittest.TestCase):

    def _job(self, root, *, expected, written=True):
        tmp = root / "a.partial.ab12.mp4"
        if written:
            tmp.write_bytes(b"partial")
        return nonai_job.Job({"tmp": str(tmp), "expected_duration": expected})

    def test_the_partials_duration_over_the_sources_rounded(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=200.0)

            with patch("util.ffprobe.duration_seconds", return_value=75.0):
                assert nonai_encode.percent_encoded(job) == 38

    def test_an_output_that_has_overrun_its_source_still_reads_as_100(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0)

            with patch("util.ffprobe.duration_seconds", return_value=140.0):
                assert nonai_encode.percent_encoded(job) == 100

    def test_an_unprobeable_partial_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0)

            with patch("util.ffprobe.duration_seconds", return_value=None):
                assert nonai_encode.percent_encoded(job) is None

    def test_a_partial_not_written_yet_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0, written=False)

            assert nonai_encode.percent_encoded(job) is None

    def test_a_source_of_unknown_length_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=0.0)

            with patch("util.ffprobe.duration_seconds", return_value=50.0):
                assert nonai_encode.percent_encoded(job) is None


class TestOverran(unittest.TestCase):
    SETTINGS = nonai_encode.EncodeSettings(max_runtime_hours=3)
    CAP_SECONDS = 3 * 3600

    def test_under_the_cap_is_not_an_overrun(self):
        started = 1_000.0
        job = nonai_job.Job({"started_at": started})

        assert not nonai_encode.overran(job, self.SETTINGS, now=started + self.CAP_SECONDS)

    def test_past_the_cap_is(self):
        started = 1_000.0
        job = nonai_job.Job({"started_at": started})

        assert nonai_encode.overran(job, self.SETTINGS, now=started + self.CAP_SECONDS + 1)

    def test_a_long_freeze_keeps_a_slow_encode_under_the_cap(self):
        started = 1_000.0
        job = nonai_job.Job({"started_at": started, "suspended_seconds": self.CAP_SECONDS})

        assert not nonai_encode.overran(job, self.SETTINGS, now=started + 2 * self.CAP_SECONDS)


class TestComputerBusyChecks:
    SETTINGS = nonai_encode.EncodeSettings()

    def checks(self, **kwargs):
        options = {"asked_for": False, "ai_waiting": False, **kwargs}
        return nonai_encode.busy_checks(Path("cooldown.json"), self.SETTINGS, **options)

    def test_the_reasons_are_checked_in_the_order_that_decides_which_one_is_given(self):
        reasons = [reason for reason, _ in self.checks()]

        assert reasons == [
            "user_present", "topaz_busy", "low_ram", "ai_clips_waiting", "cooldown",
            nonai_encode.topaz.SIGN_IN_EXPIRED,
        ]

    def test_a_request_from_the_user_skips_the_presence_and_cooldown_checks(self):
        applies = dict(self.checks(asked_for=True))

        assert not applies["user_present"]()
        assert not applies["cooldown"]()

    def test_clips_waiting_for_the_ai_stage_apply_only_when_told_so(self):
        assert dict(self.checks(ai_waiting=True))["ai_clips_waiting"]()
        assert not dict(self.checks())["ai_clips_waiting"]()


if __name__ == "__main__":
    unittest.main()


class TestUserPresent(unittest.TestCase):
    SETTINGS = nonai_encode.EncodeSettings()

    def test_an_idle_time_that_cannot_be_read_counts_as_the_user_being_present(self):
        def unreadable():
            raise OSError

        assert nonai_encode.user_present(self.SETTINGS, idle_seconds=unreadable)

    def test_input_older_than_a_reading_pause_means_the_user_is_away(self):
        away = self.SETTINGS.away_once_idle_past_a_reading_pause_seconds + 1
        assert not nonai_encode.user_present(self.SETTINGS, idle_seconds=lambda: away)
