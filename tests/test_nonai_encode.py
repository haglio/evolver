"""The detached encode, asked about directly rather than through a pipeline tick."""

import unittest
from pathlib import Path
from unittest.mock import patch

import config
from tasks import nonai_encode
from tests.temp_helpers import workspace_temp_dir


class TestParseTopazCommand(unittest.TestCase):
    """Reading an orphaned encode's input and output back off its command line.

    Library paths hold spaces as a matter of course ("0 unsorted", "1 could use
    work"), so the quoted forms are the ordinary case here, not the exotic one.
    """

    def test_reads_a_quoted_input_and_a_quoted_output(self):
        source, out = nonai_encode._parse_topaz_command(
            'ffmpeg.exe -i "C:/lib/0 unsorted/scene one.mp4" -vf x '
            '"C:/lib/3 done/scene one.partial.ab12.mp4"'
        )

        self.assertEqual(source, Path("C:/lib/0 unsorted/scene one.mp4"))
        self.assertEqual(out, Path("C:/lib/3 done/scene one.partial.ab12.mp4"))

    def test_reads_unquoted_ones_too(self):
        source, out = nonai_encode._parse_topaz_command(
            "ffmpeg.exe -i /lib/a.mp4 -vf x /lib/a.partial.ab12.mp4"
        )

        self.assertEqual(source, Path("/lib/a.mp4"))
        self.assertEqual(out, Path("/lib/a.partial.ab12.mp4"))

    def test_a_command_line_with_no_input_names_neither(self):
        self.assertEqual(nonai_encode._parse_topaz_command("ffmpeg.exe -version"),
                         (None, None))

    def test_an_empty_command_line_names_neither(self):
        self.assertEqual(nonai_encode._parse_topaz_command(""), (None, None))


class TestPercentEncoded(unittest.TestCase):
    """How far the running encode has got, read off the partial it is writing.

    ffmpeg writes fragmented mp4, so the partial is probeable mid-write and its
    duration over the source's is the progress.
    """

    def _job(self, root, *, expected, written=True):
        tmp = root / "a.partial.ab12.mp4"
        if written:
            tmp.write_bytes(b"partial")
        return {"tmp": str(tmp), "expected_duration": expected}

    def test_the_partials_duration_over_the_sources_rounded(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=200.0)

            with patch("util.ffprobe.duration_seconds", return_value=75.0):
                self.assertEqual(nonai_encode.percent_encoded(job), 38)

    def test_an_output_that_has_overrun_its_source_still_reads_as_100(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0)

            with patch("util.ffprobe.duration_seconds", return_value=140.0):
                self.assertEqual(nonai_encode.percent_encoded(job), 100)

    def test_an_unprobeable_partial_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0)

            with patch("util.ffprobe.duration_seconds", return_value=None):
                self.assertIsNone(nonai_encode.percent_encoded(job))

    def test_a_partial_not_written_yet_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=100.0, written=False)

            self.assertIsNone(nonai_encode.percent_encoded(job))

    def test_a_source_of_unknown_length_has_no_percentage(self):
        with workspace_temp_dir() as root:
            job = self._job(root, expected=0.0)

            with patch("util.ffprobe.duration_seconds", return_value=50.0):
                self.assertIsNone(nonai_encode.percent_encoded(job))


class TestActiveRuntime(unittest.TestCase):
    """Wall clock since the encode started, minus the time it spent frozen.

    The runtime cap exists to catch a *stuck* encode; hours parked while the
    user was at the machine are not the encode's fault. `now` is an argument so
    that arithmetic can be asked exactly rather than raced against the clock.
    """

    def test_a_plain_run_is_the_time_since_it_started(self):
        job = {"started_at": 1_000.0}

        self.assertEqual(nonai_encode.active_runtime(job, now=4_600.0), 3_600.0)

    def test_time_already_banked_as_suspended_is_not_charged(self):
        job = {"started_at": 1_000.0, "suspended_seconds": 600.0}

        self.assertEqual(nonai_encode.active_runtime(job, now=4_600.0), 3_000.0)

    def test_a_freeze_still_in_progress_is_not_charged_either(self):
        """Otherwise a machine left in use overnight would look like a stuck
        encode and be killed for overrunning."""
        job = {"started_at": 1_000.0, "suspended": True, "suspended_at": 2_000.0}

        self.assertEqual(nonai_encode.active_runtime(job, now=4_600.0), 1_000.0)

    def test_a_banked_freeze_and_a_live_one_both_count(self):
        job = {"started_at": 1_000.0, "suspended_seconds": 600.0,
               "suspended": True, "suspended_at": 3_000.0}

        self.assertEqual(nonai_encode.active_runtime(job, now=4_600.0), 1_400.0)

    def test_a_record_with_no_start_time_reads_as_having_just_started(self):
        """Pinned rather than endorsed: a job whose `started_at` went missing
        can never overrun, which finding tasks/design/014 files as a defect of
        the untyped record. Changing it is a behaviour change and not this
        item's."""
        self.assertEqual(nonai_encode.active_runtime({}, now=4_600.0), 0.0)


class TestOverran(unittest.TestCase):
    def test_under_the_cap_is_not_an_overrun(self):
        started = 1_000.0
        job = {"started_at": started}
        cap_seconds = config.NONAI_MAX_RUNTIME_HOURS * 3600

        self.assertFalse(nonai_encode.overran(job, now=started + cap_seconds))

    def test_past_the_cap_is(self):
        started = 1_000.0
        job = {"started_at": started}
        cap_seconds = config.NONAI_MAX_RUNTIME_HOURS * 3600

        self.assertTrue(nonai_encode.overran(job, now=started + cap_seconds + 1))

    def test_a_long_freeze_keeps_a_slow_encode_under_the_cap(self):
        started = 1_000.0
        cap_seconds = config.NONAI_MAX_RUNTIME_HOURS * 3600
        job = {"started_at": started, "suspended_seconds": cap_seconds}

        self.assertFalse(nonai_encode.overran(job, now=started + 2 * cap_seconds))


if __name__ == "__main__":
    unittest.main()
