"""How far through the non-AI upscale project the library is, by running time.

The unit these are about is seconds of video, not clips: the number that made
this worth writing is that the real library was 59% upscaled by clip and 29% by
running time, because the short clips went first.
"""

import unittest

from tasks import nonai_progress
from tests.temp_helpers import (
    make_video,
    override_config,
    workspace_temp_dir,
)
from tests.temp_helpers import (
    nonai_library_overrides as library_overrides,
)
from util import sidecar, video_type


def lasting(video, seconds):
    """*video*, with *seconds* recorded on its sidecar as the kinds stage would."""
    path = sidecar.sidecar_path(video)
    sidecar.write(path, video_type.timed(sidecar.read(path), seconds))
    return video


class TestWhatIsBehindAndAhead(unittest.TestCase):
    def test_adds_up_the_queue_and_the_upscales_the_library_already_has(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                queued = lasting(
                    make_video(non_ai / "alpha" / "0 unsorted" / "Jane Doe scene 1.mp4"),
                    600.0,
                )
                lasting(
                    make_video(non_ai / "alpha" / "3_good_to_go" / "processed"
                               / "Jane Doe scene 2_apo8_iris2.mp4"),
                    200.0,
                )

                progress = nonai_progress.so_far([queued])

            self.assertEqual(progress.done_seconds, 200.0)
            self.assertEqual(progress.remaining_seconds, 600.0)
            self.assertEqual(progress.unmeasured, 0)

    def test_the_percentage_is_of_running_time_not_of_clips(self):
        """Three of four clips done and a quarter of the project done are the
        same library — which is the whole reason a count would not do."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                done = non_ai / "alpha" / "3_good_to_go" / "processed"
                for index in (1, 2, 3):
                    lasting(make_video(done / f"Jane Doe short {index}_apo8_iris2.mp4"), 60.0)
                queued = lasting(
                    make_video(non_ai / "alpha" / "0 unsorted" / "Jane Doe scene 3.mp4"),
                    540.0,
                )

                progress = nonai_progress.so_far([queued])

            self.assertEqual(progress.percent, 25)

    def test_an_empty_project_has_no_percentage_rather_than_zero(self):
        """A library whose running times nothing has recorded yet has no
        answer; one with nothing upscaled has the answer zero."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            with override_config(**overrides):
                self.assertIsNone(nonai_progress.so_far([]).percent)

    def test_nothing_upscaled_yet_reads_as_zero_rather_than_as_no_answer(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                queued = lasting(
                    make_video(non_ai / "alpha" / "0 unsorted" / "Jane Doe scene 4.mp4"),
                    600.0,
                )

                self.assertEqual(nonai_progress.so_far([queued]).percent, 0)


class TestWhatItWillNotGuessAt(unittest.TestCase):
    def test_a_video_nothing_has_measured_is_counted_apart(self):
        """It goes in neither total, so the percentage stays a percentage of
        what the library can actually see of itself."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                queued = lasting(
                    make_video(non_ai / "alpha" / "0 unsorted" / "Jane Doe scene 5.mp4"),
                    300.0,
                )
                unmeasured = make_video(
                    non_ai / "alpha" / "0 unsorted" / "Jane Doe scene 6.mp4"
                )
                make_video(non_ai / "alpha" / "3_good_to_go" / "processed"
                           / "Jane Doe scene 7_apo8_iris2.mp4")

                progress = nonai_progress.so_far([queued, unmeasured])

            self.assertEqual(progress.remaining_seconds, 300.0)
            self.assertEqual(progress.done_seconds, 0.0)
            self.assertEqual(progress.unmeasured, 2)


class TestWhatCountsAsDone(unittest.TestCase):
    def test_an_original_with_two_variants_is_one_video_of_the_project(self):
        """A second recipe, or a version saved under a name of its own, is not
        a second video's worth of work."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                done = non_ai / "alpha" / "3_good_to_go" / "processed"
                lasting(make_video(done / "Jane Doe scene 8_apo8_iris2.mp4"), 400.0)
                lasting(make_video(done / "Jane Doe scene 8_topaz.mp4"), 400.0)

                progress = nonai_progress.so_far([])

            self.assertEqual(progress.done_seconds, 400.0)

    def test_an_original_still_in_the_library_is_not_counted_twice(self):
        """The original of an upscale is retired, but not always at once, and a
        copy left standing is the same one video."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                lasting(make_video(non_ai / "alpha" / "2 do not need work"
                                   / "Jane Doe scene 9.mp4"), 400.0)
                lasting(make_video(non_ai / "alpha" / "3_good_to_go" / "processed"
                                   / "Jane Doe scene 9_apo8_iris2.mp4"), 400.0)

                progress = nonai_progress.so_far([])

            self.assertEqual(progress.done_seconds, 400.0)

    def test_a_video_the_project_cannot_reach_is_in_neither_total(self):
        """A clip parked where a human still has to trim it is not queued and
        not upscaled; counting it as either would misreport the project."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides):
                lasting(make_video(non_ai / "alpha" / "1 could use work"
                                   / "1_originals_needing_trimming"
                                   / "Jane Doe scene 10.mp4"), 3600.0)
                lasting(make_video(non_ai / "alpha" / "3_good_to_go" / "processed"
                                   / "Jane Doe scene 11_apo8_iris2.mp4"), 400.0)

                progress = nonai_progress.so_far([])

            self.assertEqual(
                (progress.done_seconds, progress.remaining_seconds, progress.unmeasured),
                (400.0, 0.0, 0),
            )

    def test_a_bucket_the_non_ai_stages_exclude_is_not_the_project(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            with override_config(**overrides,
                                 NONAI_EXCLUDED_BUCKETS={"actually_AI_but_funscripted"}):
                lasting(make_video(non_ai / "actually_AI_but_funscripted"
                                   / "3_good_to_go" / "processed"
                                   / "Jane Doe scene 12_apo8_iris2.mp4"), 400.0)

                progress = nonai_progress.so_far([])

            self.assertEqual(progress.done_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
