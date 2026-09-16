"""What the upscale queue window is handed to show.

One list: row 1 is the video being upscaled (or the one that starts next), and
the head says what it is doing. Everything here is fabricated: buckets named the
way the committed example names them, and videos called a, b and c.
"""
from __future__ import annotations

import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from tasks import nonai_lineup
from tests.temp_helpers import (
    make_video,
    override_config,
    workspace_temp_dir,
    write_job,
    write_sidecar,
)
from tests.temp_helpers import nonai_library_overrides as library_overrides
from util import nonai_job, sidecar, upscale_lineup


@contextmanager
def running_encode(*, alive=True, percent=50):
    """The two things the window asks about a live encode, answered.

    Whether the pid is still a process, and how far the partial it is writing
    has got -- an ffprobe, which no test spawns.
    """
    with ExitStack() as stack:
        stack.enter_context(patch("util.processes.is_running", return_value=alive))
        stack.enter_context(patch("tasks.nonai_encode.percent_encoded",
                                  return_value=percent))
        yield


def videos(lineup):
    return [entry.video for entry in lineup.rows]


class TestTheList(unittest.TestCase):
    def test_an_empty_library_has_no_rows_and_nothing_on_the_first(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)

            with override_config(**overrides):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup, upscale_lineup.Lineup(rows=(), head=None))

    def test_the_rows_come_in_the_order_the_stage_would_take_them(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            make_video(non_ai / "larkin" / "0 unsorted" / "b.mp4")
            overrides["NONAI_PRIORITY_MANIFEST"].write_text(
                "larkin/0 unsorted/b.mp4\n", encoding="utf-8")

            with override_config(**overrides):
                lineup = nonai_lineup.current()

            self.assertEqual(videos(lineup),
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/a.mp4"])
            self.assertEqual([entry.pinned for entry in lineup.rows], [True, False])

    def test_with_nothing_in_flight_row_one_is_simply_next(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            with override_config(**overrides):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.head, upscale_lineup.Head(upscale_lineup.NEXT))
            self.assertFalse(lineup.head.runs_now)

    def test_a_video_is_called_by_its_recorded_title_where_it_has_one(self):
        """The title the library records is what the other apps show; a video
        with none falls back to its file name, as they do."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            titled = make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            make_video(non_ai / "larkin" / "0 unsorted" / "b.mp4")
            with override_config(**overrides):
                write_sidecar(sidecar.sidecar_path(titled),
                              {"title": "Jane Doe - Alpha Study 3",
                               "video": {"duration_seconds": 754.0}})

                lineup = nonai_lineup.current()

            self.assertEqual([(entry.name, entry.seconds) for entry in lineup.rows],
                             [("Jane Doe - Alpha Study 3", 754.0), ("b", None)])


class TestRowOne(unittest.TestCase):
    """Row 1 is whatever the machine is on, ahead of the order the stage keeps."""

    def test_the_video_in_flight_is_row_one_whatever_the_order_says(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            write_job(root, overrides)

            with override_config(**overrides), running_encode(percent=41):
                lineup = nonai_lineup.current()

            self.assertEqual(videos(lineup),
                             ["larkin/0 unsorted/busy.mp4", "larkin/0 unsorted/a.mp4"])
            self.assertEqual(lineup.head,
                             upscale_lineup.Head(upscale_lineup.UPSCALING, percent=41))
            self.assertFalse(lineup.head.runs_now)

    def test_an_encode_frozen_by_your_presence_is_paused(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True)

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.head.state, upscale_lineup.PAUSED)

    def test_an_encode_you_asked_for_runs_now(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, on_request=True)

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.head.state, upscale_lineup.ASKED_FOR)
            self.assertTrue(lineup.head.runs_now)

    def test_an_encode_whose_process_has_ended_is_finishing(self):
        """Its output is promoted on the next run, which is when the video
        leaves the queue for good."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            with override_config(**overrides), running_encode(alive=False):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.head.state, upscale_lineup.FINISHING)
            self.assertFalse(lineup.head.runs_now)

    def test_a_video_asked_for_that_has_not_started_is_row_one_and_runs_now(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            nonai_job.save_request(overrides["NONAI_REQUEST_FILE"],
                                   nonai_job.Request("larkin/0 unsorted/b.mp4",
                                                     held_back="low_ram"))

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(videos(lineup),
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/a.mp4"])
            self.assertEqual(lineup.head, upscale_lineup.Head(upscale_lineup.STARTING,
                                                              held_back="low_ram"))
            self.assertTrue(lineup.head.runs_now)


if __name__ == "__main__":
    unittest.main()
