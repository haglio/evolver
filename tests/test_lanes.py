"""The library's three lanes, walked once for every stage that asks."""
from __future__ import annotations

import unittest

from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
from util import lanes


class TestAiClips(unittest.TestCase):
    def test_each_sorted_clip_knows_its_source_orientation_and_upscale(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                video = touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_b.partial.mp4")

                clips = list(lanes.ai_clips())
                upscales = [clip.upscale for clip in clips]

        self.assertEqual([(c.video, c.source, c.orientation) for c in clips],
                         [(video, "provider2", "portrait")])
        self.assertEqual(upscales, [lib.outbox / "portrait" / "provider2" / "clip_a_topaz.mp4"])

    def test_no_sorted_folder_means_no_clips(self):
        with workspace_temp_dir() as root:
            with LaneLibrary(root).config():
                self.assertEqual(list(lanes.ai_clips()), [])


class TestGenauClips(unittest.TestCase):
    def test_lists_the_delivered_loops_and_nothing_still_being_written(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                loop = touch_video(lib.genau_clips / "loop_2_topaz.mp4")
                touch_video(lib.genau_clips / "loop_3.partial.mp4")
                (lib.genau_clips / "notes.txt").write_text("x", encoding="utf-8")

                self.assertEqual(list(lanes.genau_clips()), [loop])


class TestSentLanes(unittest.TestCase):
    def test_each_lane_names_its_inbox_folder_and_the_column_it_is_withdrawn_in(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(genau_source="example-loop-clips"):
                sent = lanes.sent_lanes()

                self.assertEqual([(lane.source, lane.unsent_column) for lane in sent],
                                 [("origenerator", "evolver_unsent_at"),
                                  ("example-loop-clips", "genau_unsent_at")])

    def test_only_the_genau_lane_delivers_its_clips_out_of_the_library(self):
        # The other lane's clips rest in the outbox, so there is nowhere else to
        # look for a copy of one; this lane's leave for the folder Genau plays
        # from, which is the whole reason a withdrawal cannot be done from the
        # app that sent them.
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                library_lane, genau_lane = lanes.sent_lanes()

                self.assertIsNone(library_lane.delivered_dir)
                self.assertEqual(genau_lane.delivered_dir, lib.genau_clips)


class TestNonAiVideos(unittest.TestCase):
    def test_walks_every_bucket_in_a_stable_order(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                later = touch_video(lib.non_ai / "beta" / "scenes" / "scene.mp4")
                first = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-1.mp4")

                self.assertEqual(lanes.non_ai_videos(), [first, later])

    def test_no_non_ai_folder_means_no_videos(self):
        with workspace_temp_dir() as root:
            with LaneLibrary(root).config():
                self.assertEqual(lanes.non_ai_videos(), [])
