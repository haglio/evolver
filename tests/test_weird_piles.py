from __future__ import annotations

import unittest
from pathlib import Path

from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from util import weird_piles
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


class TestWhereAVideoMarkedWeirdCameFrom(_InALibrary):
    def test_an_upscale_goes_back_where_the_upscale_stage_filed_it(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene one.mp4")
        marked = touch_video(self.lib.weird / "scene one_topaz.mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(found.video, marked)
        self.assertEqual(
            found.restores_to,
            self.lib.outbox / "portrait" / "example-source" / "scene one_topaz.mp4")

    def test_a_second_video_marked_under_a_taken_name_goes_back_under_its_own(self):
        touch_video(self.lib.sorted_dir / "example-source" / "landscape" / "scene two.mp4")
        touch_video(self.lib.weird / "scene two_topaz__dup1.mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(
            found.restores_to,
            self.lib.outbox / "landscape" / "example-source" / "scene two_topaz.mp4")

    def test_of_two_sources_sharing_a_name_it_restores_to_the_one_missing_its_upscale(self):
        for source in ("example-source", "example-loop-clips"):
            touch_video(self.lib.sorted_dir / source / "portrait" / "loop_3.mkv")
        touch_video(self.lib.outbox / "portrait" / "example-source" / "loop_3_topaz.mp4")
        touch_video(self.lib.weird / "loop_3_topaz.mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(
            found.restores_to,
            self.lib.outbox / "portrait" / "example-loop-clips" / "loop_3_topaz.mp4")
        self.assertEqual(found.upscaled_from,
                         self.lib.sorted_dir / "example-loop-clips" / "portrait" / "loop_3.mkv")

    def test_a_copy_left_outside_the_orientation_folders_is_no_upscale_s_source(self):
        touch_video(self.lib.sorted_dir / "example-source" / "loop_4.mp4")
        touch_video(self.lib.weird / "loop_4_topaz.mp4")

        [found] = weird_piles.marked_weird()

        self.assertIsNone(found.restores_to)

    def test_a_genau_clip_restores_to_its_own_place_in_genaus_folder(self):
        top = touch_video(self.lib.genau_weird / "loop_5_topaz.mp4")
        inside = touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_6_topaz.mp4")

        found = {marked.video: marked.restores_to for marked in weird_piles.marked_weird()}

        self.assertEqual(found, {
            top: self.lib.genau_clips / "loop_5_topaz.mp4",
            inside: self.lib.genau_clips / "2D" / "AI" / "loop_6_topaz.mp4",
        })

    def test_a_genau_clip_was_upscaled_from_the_copy_its_lane_failed_to_retire(self):
        left_behind = touch_video(self.lib.sorted_dir / "example-loop-clips" / "portrait" / "loop_8.mp4")
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "loop_8.mp4")
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_8_topaz (2).mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(found.upscaled_from, left_behind)

    def test_a_clip_whose_place_has_been_taken_since_has_nowhere_to_go_back_to(self):
        touch_video(self.lib.genau_clips / "loop_7_topaz.mp4")
        touch_video(self.lib.genau_weird / "loop_7_topaz.mp4")

        [found] = weird_piles.marked_weird()

        self.assertIsNone(found.restores_to)

    def test_a_video_no_upscale_explains_goes_back_where_its_record_still_is(self):
        scene = self.lib.non_ai / "example-bucket" / "full" / "scene three.mp4"
        _a_record_for(scene)
        touch_video(self.lib.weird / "scene three.mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(found.restores_to, scene)

    def test_a_namesake_still_in_its_place_is_not_where_the_video_goes_back(self):
        scene = self.lib.non_ai / "example-bucket" / "full" / "scene four.mp4"
        _a_record_for(scene)
        _a_record_for(touch_video(self.lib.non_ai / "other-bucket" / "scene four.mp4"))
        touch_video(self.lib.weird / "scene four.mp4")

        [found] = weird_piles.marked_weird()

        self.assertEqual(found.restores_to, scene)

    def test_two_places_a_video_could_have_left_are_no_answer(self):
        for bucket in ("example-bucket", "other-bucket"):
            _a_record_for(self.lib.non_ai / bucket / "scene five.mp4")
        touch_video(self.lib.weird / "scene five.mp4")

        [found] = weird_piles.marked_weird()

        self.assertIsNone(found.restores_to)


class TestRestoring(_InALibrary):
    def test_the_video_is_back_where_it_came_from_and_gone_from_the_pile(self):
        marked = touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_9_topaz.mp4")
        [found] = weird_piles.marked_weird()

        with self.assertLogs("util.weird_piles", level="INFO") as said:
            weird_piles.restore(found)

        self.assertFalse(marked.exists())
        self.assertTrue((self.lib.genau_clips / "2D" / "AI" / "loop_9_topaz.mp4").is_file())
        self.assertEqual(said.records[0].args, (marked, found.restores_to))

    def test_the_funscript_that_followed_it_into_the_pile_comes_back_with_its_mark(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene six.mp4")
        marked = touch_video(self.lib.weird / "scene six_topaz__dup2.mp4")
        _a_script_for(marked, generated=True)
        [found] = weird_piles.marked_weird()

        weird_piles.restore(found)

        script = script_path_for_video(found.restores_to)
        self.assertTrue(script.is_file())
        self.assertTrue(is_marked_generated(script))
        self.assertFalse(script_path_for_video(marked).exists())

    def test_a_video_with_nowhere_to_go_back_to_stays_in_the_pile(self):
        marked = touch_video(self.lib.weird / "scene seven.mp4")
        [found] = weird_piles.marked_weird()

        with self.assertRaises(ValueError):
            weird_piles.restore(found)

        self.assertTrue(marked.is_file())

    def test_a_place_taken_since_the_list_was_read_keeps_what_took_it(self):
        marked = touch_video(self.lib.genau_weird / "loop_10_topaz.mp4")
        [found] = weird_piles.marked_weird()
        taker = touch_video(self.lib.genau_clips / "loop_10_topaz.mp4")
        taker.write_bytes(b"another")

        with self.assertRaises(FileExistsError):
            weird_piles.restore(found)

        self.assertTrue(marked.is_file())
        self.assertEqual(taker.read_bytes(), b"another")


class TestDeletingPermanently(_InALibrary):
    def test_the_video_goes_and_so_does_the_copy_it_was_upscaled_from(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene eight.mp4")
        marked = touch_video(self.lib.weird / "scene eight_topaz.mp4")
        [found] = weird_piles.marked_weird()

        weird_piles.delete_permanently(found)

        self.assertFalse(marked.exists())
        self.assertFalse(source.exists())

    def test_its_own_record_goes_and_every_namesake_keeps_its_own(self):
        touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene nine.mp4")
        touch_video(self.lib.weird / "scene nine_topaz.mp4")
        [found] = weird_piles.marked_weird()
        own = _a_record_for(found.restores_to)
        namesakes = [
            _a_record_for(touch_video(self.lib.outbox / "landscape" / "example-source" / "scene nine_topaz.mp4")),
            _a_record_for(touch_video(self.lib.non_ai / "example-bucket" / "0 unsorted" / "scene nine_topaz.mp4")),
        ]

        weird_piles.delete_permanently(found)

        self.assertFalse(own.exists())
        self.assertTrue(all(record.exists() for record in namesakes))

    def test_every_funscript_it_and_its_copy_held_goes_with_its_mark(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene ten.mp4")
        marked = touch_video(self.lib.weird / "scene ten_topaz.mp4")
        [found] = weird_piles.marked_weird()
        scripts = [_a_script_for(video, generated=True) for video in (marked, found.restores_to, source)]

        weird_piles.delete_permanently(found)

        self.assertEqual([script for script in scripts if script.exists()], [])
        self.assertEqual([script for script in scripts if is_marked_generated(script)], [])

    def test_a_genau_clips_sound_goes_with_it(self):
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_11_topaz.mp4")
        sound = touch_video(self.lib.genau_audio / "loop_11_topaz.mp3")
        [found] = weird_piles.marked_weird()

        weird_piles.delete_permanently(found)

        self.assertFalse(sound.exists())

    def test_a_sound_another_clip_of_that_name_still_plays_is_kept(self):
        touch_video(self.lib.genau_weird / "2D" / "AI" / "loop_12_topaz.mp4")
        touch_video(self.lib.genau_weird / "loop_12_topaz.mp4")
        sound = touch_video(self.lib.genau_audio / "loop_12_topaz.mp3")
        first, _second = weird_piles.marked_weird()

        weird_piles.delete_permanently(first)

        self.assertTrue(sound.exists())

    def test_the_log_names_everything_it_deleted_the_copy_first(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene eleven.mp4")
        marked = touch_video(self.lib.weird / "scene eleven_topaz.mp4")
        [found] = weird_piles.marked_weird()
        record = _a_record_for(found.restores_to)
        script = _a_script_for(marked)

        with self.assertLogs("util.weird_piles", level="INFO") as said:
            weird_piles.delete_permanently(found)

        self.assertEqual([entry.args[0] for entry in said.records], [source, marked, record, script])


if __name__ == "__main__":
    unittest.main()
