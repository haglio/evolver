from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks import nonai_encode
from tests.temp_helpers import workspace_temp_dir


class TestParseTopazCommand(unittest.TestCase):
    def test_reads_a_quoted_input_and_a_quoted_output(self):
        source, out = nonai_encode._parse_topaz_command(
            'ffmpeg.exe -i "C:/lib/0 unsorted/scene one.mp4" -vf x '
            '"C:/lib/3 done/scene one.partial.ab12.mp4"'
        )

        assert source == Path("C:/lib/0 unsorted/scene one.mp4")
        assert out == Path("C:/lib/3 done/scene one.partial.ab12.mp4")

    def test_reads_unquoted_ones_too(self):
        source, out = nonai_encode._parse_topaz_command(
            "ffmpeg.exe -i /lib/a.mp4 -vf x /lib/a.partial.ab12.mp4"
        )

        assert source == Path("/lib/a.mp4")
        assert out == Path("/lib/a.partial.ab12.mp4")

    def test_a_command_line_with_no_input_names_neither(self):
        assert nonai_encode._parse_topaz_command("ffmpeg.exe -version") == (None, None)

    def test_an_empty_command_line_names_neither(self):
        assert nonai_encode._parse_topaz_command("") == (None, None)


class TestPercentEncoded(unittest.TestCase):

    def _job(self, root, *, expected, written=True):
        tmp = root / "a.partial.ab12.mp4"
        if written:
            tmp.write_bytes(b"partial")
        return {"tmp": str(tmp), "expected_duration": expected}

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


class TestActiveRuntime(unittest.TestCase):
    def test_a_plain_run_is_the_time_since_it_started(self):
        job = {"started_at": 1_000.0}

        assert nonai_encode.active_runtime(job, now=4600.0) == 3600.0

    def test_time_already_banked_as_suspended_is_not_charged(self):
        job = {"started_at": 1_000.0, "suspended_seconds": 600.0}

        assert nonai_encode.active_runtime(job, now=4600.0) == 3000.0

    def test_a_freeze_still_in_progress_is_not_charged_either(self):
        job = {"started_at": 1_000.0, "suspended": True, "suspended_at": 2_000.0}

        assert nonai_encode.active_runtime(job, now=4600.0) == 1000.0

    def test_a_banked_freeze_and_a_live_one_both_count(self):
        job = {"started_at": 1_000.0, "suspended_seconds": 600.0,
               "suspended": True, "suspended_at": 3_000.0}

        assert nonai_encode.active_runtime(job, now=4600.0) == 1400.0

    def test_a_record_with_no_start_time_reads_as_having_just_started(self):
        assert nonai_encode.active_runtime({}, now=4600.0) == 0.0


class TestOverran(unittest.TestCase):
    SETTINGS = nonai_encode.EncodeSettings(max_runtime_hours=3)
    CAP_SECONDS = 3 * 3600

    def test_under_the_cap_is_not_an_overrun(self):
        started = 1_000.0
        job = {"started_at": started}

        assert not nonai_encode.overran(job, self.SETTINGS, now=started + self.CAP_SECONDS)

    def test_past_the_cap_is(self):
        started = 1_000.0
        job = {"started_at": started}

        assert nonai_encode.overran(job, self.SETTINGS, now=started + self.CAP_SECONDS + 1)

    def test_a_long_freeze_keeps_a_slow_encode_under_the_cap(self):
        started = 1_000.0
        job = {"started_at": started, "suspended_seconds": self.CAP_SECONDS}

        assert not nonai_encode.overran(job, self.SETTINGS, now=started + 2 * self.CAP_SECONDS)


class TestComputerBusyReason:
    SETTINGS = nonai_encode.EncodeSettings()

    @pytest.fixture(autouse=True)
    def quiet_computer(self, monkeypatch):
        monkeypatch.setattr(nonai_encode, "user_present", lambda settings: False)
        monkeypatch.setattr(nonai_encode, "topaz_pids", list)
        monkeypatch.setattr(nonai_encode.system_resources, "available_ram_gb", lambda: 1_000.0)
        monkeypatch.setattr(nonai_encode.nonai_job, "last_encode_ended_at", lambda path: 0.0)
        monkeypatch.setattr(nonai_encode.topaz, "sign_in_expired", lambda: False)

    def busy(self, **kwargs):
        return nonai_encode.computer_busy_reason(Path("cooldown.json"), self.SETTINGS, **kwargs)

    def test_a_quiet_computer_has_no_reason_to_wait(self):
        assert self.busy() == ""

    def test_the_user_being_present_comes_before_topaz_being_busy(self, monkeypatch):
        monkeypatch.setattr(nonai_encode, "user_present", lambda settings: True)
        monkeypatch.setattr(nonai_encode, "topaz_pids", lambda: [4])

        assert self.busy() == "user_present"

    def test_a_request_from_the_user_ignores_their_presence(self, monkeypatch):
        monkeypatch.setattr(nonai_encode, "user_present", lambda settings: True)

        assert self.busy(asked_for=True) == ""

    def test_topaz_running_comes_before_low_memory(self, monkeypatch):
        monkeypatch.setattr(nonai_encode, "topaz_pids", lambda: [4])
        monkeypatch.setattr(nonai_encode.system_resources, "available_ram_gb", lambda: 0.0)

        assert self.busy() == "topaz_busy"

    def test_clips_waiting_for_the_ai_stage_hold_the_encode_back(self):
        assert self.busy(ai_waiting=True) == "ai_clips_waiting"

    def test_a_recent_encode_means_cooldown_unless_the_user_asked(self, monkeypatch):
        monkeypatch.setattr(nonai_encode.time, "time", lambda: 100.0)
        monkeypatch.setattr(nonai_encode.nonai_job, "last_encode_ended_at", lambda path: 99.0)

        assert self.busy() == "cooldown"
        assert self.busy(asked_for=True) == ""

    def test_an_expired_topaz_sign_in_is_the_last_reason_checked(self, monkeypatch):
        monkeypatch.setattr(nonai_encode.topaz, "sign_in_expired", lambda: True)

        assert self.busy() == nonai_encode.topaz.SIGN_IN_EXPIRED
        assert self.busy(ai_waiting=True) == "ai_clips_waiting"


if __name__ == "__main__":
    unittest.main()


class TestUserPresent(unittest.TestCase):
    SETTINGS = nonai_encode.EncodeSettings()

    def test_an_idle_time_that_cannot_be_read_counts_as_the_user_being_present(self):
        def unreadable():
            raise OSError

        assert nonai_encode.user_present(self.SETTINGS, idle_seconds=unreadable)

    def test_input_older_than_the_threshold_means_the_user_is_away(self):
        away = self.SETTINGS.user_idle_threshold_seconds + 1
        assert not nonai_encode.user_present(self.SETTINGS, idle_seconds=lambda: away)
