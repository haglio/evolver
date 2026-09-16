"""What the upscale queue window is handed to show.

Everything here is fabricated: buckets named the way the committed example
names them, and videos called a, b and c.
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
from util import nonai_job, sidecar


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


class TestLineup(unittest.TestCase):
    def test_an_empty_library_has_nothing_upscaling_and_nothing_waiting(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)

            with override_config(**overrides):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup, nonai_lineup.Lineup(now=None, up_next=()))

    def test_the_queue_comes_in_the_order_the_stage_would_take_it(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            make_video(non_ai / "larkin" / "0 unsorted" / "b.mp4")
            overrides["NONAI_PRIORITY_MANIFEST"].write_text(
                "larkin/0 unsorted/b.mp4\n", encoding="utf-8")

            with override_config(**overrides):
                lineup = nonai_lineup.current()

            self.assertEqual([entry.video for entry in lineup.up_next],
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/a.mp4"])
            self.assertEqual([entry.pinned for entry in lineup.up_next], [True, False])

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

            self.assertEqual([(entry.name, entry.seconds) for entry in lineup.up_next],
                             [("Jane Doe - Alpha Study 3", 754.0), ("b", None)])


class TestWhatIsUpscalingNow(unittest.TestCase):
    def test_the_video_in_flight_is_lifted_out_of_the_list(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            write_job(root, overrides)

            with override_config(**overrides), running_encode(percent=41):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.now.entry.video, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(lineup.now.state, nonai_lineup.UPSCALING)
            self.assertEqual(lineup.now.percent, 41)
            self.assertEqual([entry.video for entry in lineup.up_next],
                             ["larkin/0 unsorted/a.mp4"])

    def test_an_encode_frozen_by_your_presence_says_it_is_paused(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True)

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.now.state, nonai_lineup.PAUSED)

    def test_an_encode_you_asked_for_says_that_instead(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, on_request=True)

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.now.state, nonai_lineup.ASKED_FOR)

    def test_an_encode_whose_process_has_ended_is_finishing(self):
        """Its output is promoted on the next run, which is when the video
        leaves the queue for good."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            with override_config(**overrides), running_encode(alive=False):
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.now.state, nonai_lineup.FINISHING)

    def test_a_video_asked_for_that_has_not_started_is_the_one_shown(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            nonai_job.save_request(overrides["NONAI_REQUEST_FILE"],
                                   nonai_job.Request("larkin/0 unsorted/a.mp4",
                                                     held_back="low_ram"))

            with override_config(**overrides), running_encode():
                lineup = nonai_lineup.current()

            self.assertEqual(lineup.now.entry.video, "larkin/0 unsorted/a.mp4")
            self.assertEqual(lineup.now.state, nonai_lineup.STARTING)
            self.assertEqual(lineup.now.held_back, "low_ram")
            self.assertEqual(lineup.up_next, ())


if __name__ == "__main__":
    unittest.main()
