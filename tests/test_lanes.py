from __future__ import annotations

import unittest

from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir
from util import contract, lanes


class TestAiVideos(unittest.TestCase):
    def test_each_sorted_clip_knows_its_source_orientation_and_upscale(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                video = touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_b.partial.mp4")

                clips = list(lanes.ai_videos())
                upscales = [clip.upscale for clip in clips]

        assert [(c.video, c.source, c.orientation) for c in clips] == [(video, "provider2", "portrait")]
        assert upscales == [lib.kino_upscales / "portrait" / "provider2" / "clip_a_topaz.mp4"]

    def test_no_sorted_folder_means_no_clips(self):
        with workspace_temp_dir() as root, LaneLibrary(root).config():
            assert list(lanes.ai_videos()) == []


class TestWhereAnUpscaleIsKept(unittest.TestCase):
    def test_a_kino_upscale_is_kept_in_kinos_folder_by_orientation_then_source(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                assert lanes.upscale_of("provider2", "portrait", "clip") ==                     lib.kino / "2D" / "AI" / "portrait" / "provider2" / "clip_topaz.mp4"

    def test_a_genau_upscale_is_kept_where_genau_plays_its_flicks_from(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                assert lanes.upscale_of("example-loop-clips", "landscape", "loop_1") ==                     lib.genau_flicks / "2D" / "AI" / "loop_1_topaz.mp4"

    def test_a_genau_upscale_has_no_place_while_no_folder_is_laid_out_as_genaus_flicks_are(self):
        with workspace_temp_dir() as root, override_config(
                GENAU_DIR=root / "genau", GENAU_SOURCE="example-loop-clips", KINO_DIR=root / "kino"):
            assert lanes.upscale_of("example-loop-clips", "landscape", "loop_1") is None

    def test_each_lanes_trash_keeps_its_own_upscales(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                kino = lanes.upscale_of("provider2", "portrait", "clip")
                genau = lanes.upscale_of("example-loop-clips", "landscape", "loop_1")

                assert lanes.in_trash(kino) == lib.trash / "clip_topaz.mp4"
                assert lanes.in_trash(genau) == lib.genau_trash / "2D" / "AI" / "loop_1_topaz.mp4"


class TestGenauFlicks(unittest.TestCase):
    def test_every_video_in_the_2d_and_vr_folders_is_a_genau_flick(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                loop = touch_video(lib.genau_flicks / "2D" / "AI" / "loop_2_topaz.mp4")
                cut = touch_video(lib.genau_flicks / "2D" / "non_AI" / "scene one.mp4")
                vr = touch_video(lib.genau_flicks / "VR" / "scene two_180.mp4")

                assert list(lanes.genau_flicks()) == [loop, cut, vr]

    def test_finds_genaus_flicks_by_the_shape_of_their_folder_whatever_it_is_called(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                renamed = lib.genau_flicks.parent / "renamed"
                lib.genau_flicks.rename(renamed)
                flick = touch_video(renamed / "2D" / "AI" / "loop_2_topaz.mp4")

                assert list(lanes.genau_flicks()) == [flick]
                assert lanes.genau_delivery_dir() == renamed / "2D" / "AI"

    def test_finds_no_flicks_and_nowhere_to_deliver_where_no_folder_has_their_shape(self):
        with workspace_temp_dir() as root, override_config(GENAU_DIR=root / "genau"):
            assert list(lanes.genau_flicks()) == []
            assert lanes.genau_delivery_dir() is None

    def test_lists_the_delivered_loops_and_nothing_still_being_written(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                loop = touch_video(lib.genau_flicks / "loop_2_topaz.mp4")
                touch_video(lib.genau_flicks / "loop_3.partial.mp4")
                (lib.genau_flicks / "notes.txt").write_text("x", encoding="utf-8")

                assert list(lanes.genau_flicks()) == [loop]


class TestSentLanes(unittest.TestCase):
    def test_each_lane_names_its_inbox_folder_and_the_column_it_is_withdrawn_in(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(genau_source="example-loop-clips"):
                sent = lanes.sent_lanes()

                assert [(lane.source, lane.unsent_column) for lane in sent] == [("origenerator", "evolver_unsent_at"), ("example-loop-clips", "genau_unsent_at")]

    def test_each_lane_keeps_its_upscales_and_its_trash_in_its_own_folder(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                kino_lane, genau_lane = lanes.sent_lanes()

                assert (kino_lane.upscales, kino_lane.trash) == (
                    (lib.kino_upscales / "landscape" / "origenerator",
                     lib.kino_upscales / "portrait" / "origenerator"), lib.trash)
                assert (genau_lane.upscales, genau_lane.trash) == (
                    (lib.genau_flicks / "2D" / "AI",), lib.genau_trash)

    def test_no_lane_folder_is_published_in_the_contract(self):
        with override_config(GENAU_SOURCE="example-loop-clips"):
            published = contract.published_text()

            assert [lane.source for lane in lanes.sent_lanes() if f'"{lane.source}"' in published] == [], (
                "a lane's folder is library vocabulary each app reads from its own settings")


class TestNonAiVideos(unittest.TestCase):
    def test_walks_every_bucket_in_a_stable_order(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                later = touch_video(lib.non_ai / "beta" / "scenes" / "scene.mp4")
                first = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-1.mp4")

                assert lanes.non_ai_videos() == [first, later]

    def test_no_non_ai_folder_means_no_videos(self):
        with workspace_temp_dir() as root, LaneLibrary(root).config():
            assert lanes.non_ai_videos() == []
