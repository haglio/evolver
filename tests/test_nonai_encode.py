"""The detached encode, asked about directly rather than through a pipeline tick."""

import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
