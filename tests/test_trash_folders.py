from __future__ import annotations

import unittest
from pathlib import Path

from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from util import trash_folders
from util.script_library import is_marked_generated, mark_generated, script_path_for_video
from util.sidecar import sidecar_path


def _a_record_for(video: Path) -> Path:
    write_sidecar(sidecar_path(video), {})
    return sidecar_path(video)


def _a_script_for(video: Path, *, generated: bool = False) -> Path:
    script = script_path_for_video(video)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('{"actions": []}', encoding="utf-8")
    if generated:
        mark_generated(script)
    return script


class _InALibrary(unittest.TestCase):
    def setUp(self):
        workspace = workspace_temp_dir()
        self.lib = LaneLibrary(workspace.__enter__())
        self.addCleanup(workspace.__exit__, None, None, None)
        configured = self.lib.config()
        configured.__enter__()
        self.addCleanup(configured.__exit__, None, None, None)


def _all_in_trash():
    return trash_folders.marked_as(trash_folders.videos_in_trash())


class TestWhereAVideoMarkedTrashCameFrom(_InALibrary):
    def test_an_upscale_played_where_the_upscale_stage_filed_it(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene one.mp4")
        marked = touch_video(self.lib.trash / "scene one_topaz.mp4")

        [found] = _all_in_trash()

        assert found.video == marked
        assert found.played_at == self.lib.kino_upscales / "portrait" / "example-source" / "scene one_topaz.mp4"

    def test_a_second_video_marked_under_a_taken_name_played_under_its_own(self):
        touch_video(self.lib.sorted_dir / "example-source" / "landscape" / "scene two.mp4")
        touch_video(self.lib.trash / "scene two_topaz__dup1.mp4")

        [found] = _all_in_trash()

        assert found.played_at == self.lib.kino_upscales / "landscape" / "example-source" / "scene two_topaz.mp4"

    def test_of_two_sources_sharing_a_name_it_played_at_the_one_missing_its_upscale(self):
        for source in ("example-source", "example-source-two"):
            touch_video(self.lib.sorted_dir / source / "portrait" / "loop_3.mkv")
        touch_video(self.lib.kino_upscales / "portrait" / "example-source" / "loop_3_topaz.mp4")
        touch_video(self.lib.trash / "loop_3_topaz.mp4")

        [found] = _all_in_trash()

        assert found.played_at == self.lib.kino_upscales / "portrait" / "example-source-two" / "loop_3_topaz.mp4"
        assert found.upscaled_from == self.lib.sorted_dir / "example-source-two" / "portrait" / "loop_3.mkv"

    def test_a_copy_left_outside_the_orientation_folders_is_no_upscale_s_source(self):
        touch_video(self.lib.sorted_dir / "example-source" / "loop_4.mp4")
        touch_video(self.lib.trash / "loop_4_topaz.mp4")

        [found] = _all_in_trash()

        assert found.played_at is None

    def test_a_genau_clip_played_at_its_own_place_in_genaus_folder(self):
        top = touch_video(self.lib.genau_trash / "loop_5_topaz.mp4")
        inside = touch_video(self.lib.genau_trash / "2D" / "AI" / "loop_6_topaz.mp4")

        found = {marked.video: marked.played_at for marked in _all_in_trash()}

        assert found == {top: self.lib.genau_flicks / "loop_5_topaz.mp4", inside: self.lib.genau_flicks / "2D" / "AI" / "loop_6_topaz.mp4"}

    def test_a_genau_clip_was_upscaled_from_the_copy_its_lane_failed_to_retire(self):
        left_behind = touch_video(self.lib.sorted_dir / "example-loop-clips" / "portrait" / "loop_8.mp4")
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "loop_8.mp4")
        touch_video(self.lib.genau_trash / "2D" / "AI" / "loop_8_topaz (2).mp4")

        [found] = _all_in_trash()

        assert found.upscaled_from == left_behind

    def test_a_clip_whose_place_has_been_taken_since_names_no_place_it_played(self):
        touch_video(self.lib.genau_flicks / "loop_7_topaz.mp4")
        touch_video(self.lib.genau_trash / "loop_7_topaz.mp4")

        [found] = _all_in_trash()

        assert found.played_at is None

    def test_a_video_no_upscale_explains_played_where_its_record_still_is(self):
        scene = self.lib.non_ai / "example-bucket" / "full" / "scene three.mp4"
        _a_record_for(scene)
        touch_video(self.lib.trash / "scene three.mp4")

        [found] = _all_in_trash()

        assert found.played_at == scene

    def test_a_namesake_still_in_its_place_is_not_where_the_video_played(self):
        scene = self.lib.non_ai / "example-bucket" / "full" / "scene four.mp4"
        _a_record_for(scene)
        _a_record_for(touch_video(self.lib.non_ai / "other-bucket" / "scene four.mp4"))
        touch_video(self.lib.trash / "scene four.mp4")

        [found] = _all_in_trash()

        assert found.played_at == scene

    def test_two_places_a_video_could_have_left_are_no_answer(self):
        for bucket in ("example-bucket", "other-bucket"):
            _a_record_for(self.lib.non_ai / bucket / "scene five.mp4")
        touch_video(self.lib.trash / "scene five.mp4")

        [found] = _all_in_trash()

        assert found.played_at is None


class TestDeletingPermanently(_InALibrary):
    def test_the_video_goes_and_so_does_the_copy_it_was_upscaled_from(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene eight.mp4")
        marked = touch_video(self.lib.trash / "scene eight_topaz.mp4")
        [found] = _all_in_trash()

        trash_folders.delete_permanently(found)

        assert not marked.exists()
        assert not source.exists()

    def test_its_own_record_goes_and_every_namesake_keeps_its_own(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene nine.mp4")
        touch_video(self.lib.trash / "scene nine_topaz.mp4")
        [found] = _all_in_trash()
        own = _a_record_for(found.played_at)
        namesakes = [
            _a_record_for(touch_video(self.lib.kino_upscales / "landscape" / "example-source" / "scene nine_topaz.mp4")),
            _a_record_for(touch_video(self.lib.non_ai / "example-bucket" / "0 unsorted" / "scene nine_topaz.mp4")),
        ]

        trash_folders.delete_permanently(found)

        assert not own.exists()
        assert all(record.exists() for record in namesakes)

    def test_every_funscript_it_and_its_copy_held_goes_with_its_mark(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene ten.mp4")
        marked = touch_video(self.lib.trash / "scene ten_topaz.mp4")
        [found] = _all_in_trash()
        scripts = [_a_script_for(video, generated=True) for video in (marked, found.played_at, source)]

        trash_folders.delete_permanently(found)

        assert [script for script in scripts if script.exists()] == []
        assert [script for script in scripts if is_marked_generated(script)] == []

    def test_a_genau_clips_sound_goes_with_it(self):
        touch_video(self.lib.genau_trash / "2D" / "AI" / "loop_11_topaz.mp4")
        sound = touch_video(self.lib.genau_audio / "loop_11_topaz.mp3")
        [found] = _all_in_trash()

        trash_folders.delete_permanently(found)

        assert not sound.exists()

    def test_a_sound_another_clip_of_that_name_still_plays_is_kept(self):
        touch_video(self.lib.genau_trash / "2D" / "AI" / "loop_12_topaz.mp4")
        touch_video(self.lib.genau_trash / "loop_12_topaz.mp4")
        sound = touch_video(self.lib.genau_audio / "loop_12_topaz.mp3")
        first, _second = _all_in_trash()

        trash_folders.delete_permanently(first)

        assert sound.exists()

    def test_the_log_names_everything_it_deleted_the_copy_first(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene eleven.mp4")
        marked = touch_video(self.lib.trash / "scene eleven_topaz.mp4")
        [found] = _all_in_trash()
        record = _a_record_for(found.played_at)
        script = _a_script_for(marked)

        with self.assertLogs("util.trash_folders", level="INFO") as said:
            trash_folders.delete_permanently(found)

        assert [entry.args[0] for entry in said.records] == [source, marked, record, script]


if __name__ == "__main__":
    unittest.main()
