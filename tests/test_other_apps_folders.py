"""What Evolver's walkers do with Genau's folder and Origenerator's, which the shared settings place inside the video library."""
from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tasks import clip_scripts, scene_scripts, scripts_sync, stray_files
from tests.temp_helpers import (
    CarvedClipLibraryCase,
    LaneLibrary,
    override_config,
    touch_video,
    workspace_temp_dir,
)
from util import media_files, script_library, sidecar, video_locator


@contextmanager
def a_library(**extra):
    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config(**extra):
            yield lib


def _flick_in(lib: LaneLibrary, name: str = "loop_1.mp4") -> Path:
    return touch_video(lib.genau_flicks / "2D" / "AI" / name)


def _made_by_origenerator(lib: LaneLibrary, name: str = "video_1.mp4") -> Path:
    return touch_video(lib.origenerator / name)


class TestWalkingTheLibrary(unittest.TestCase):
    def test_leaves_out_genau_s_folder_and_origenerator_s(self):
        with a_library() as lib:
            own = touch_video(lib.non_ai / "example.bucket" / "scene one.mp4")
            _flick_in(lib)
            _made_by_origenerator(lib)

            self.assertEqual(set(media_files.library_videos(lib.library)), {own})

    def test_walking_one_of_them_itself_finds_what_is_in_it(self):
        with a_library() as lib:
            flick = _flick_in(lib)
            made = _made_by_origenerator(lib)

            self.assertEqual(list(media_files.library_videos(lib.genau)), [flick])
            self.assertEqual(list(media_files.library_videos(lib.origenerator)), [made])

    def test_lists_every_file_of_the_library_but_theirs(self):
        with a_library() as lib:
            notes = lib.non_ai / "example.bucket" / "notes.txt"
            for folder in (notes.parent, lib.genau, lib.origenerator):
                (folder / "notes.txt").parent.mkdir(parents=True, exist_ok=True)
                (folder / "notes.txt").write_text("notes", encoding="utf-8")

            self.assertEqual(set(media_files.library_files(lib.library)), {notes})


class TestStrayFiles(unittest.TestCase):
    def test_repairs_a_name_in_the_library_and_leaves_both_folders_as_they_are(self):
        with a_library() as lib:
            own = touch_video(lib.non_ai / "example.bucket" / "scene mp4")
            kept = [touch_video(lib.genau_flicks / "2D" / "AI" / "loop mp4"),
                    touch_video(lib.origenerator / "video_1 mp4"),
                    touch_video(lib.genau_flicks / "2D" / "AI" / "loop.funscript"),
                    touch_video(lib.origenerator / "video_1.funscript")]

            result = stray_files.run()

            self.assertEqual((result.renamed, result.rehomed_scripts, result.reported), (1, 0, []))
            self.assertTrue(own.with_name("scene.mp4").is_file())
            self.assertTrue(all(path.is_file() for path in kept))


class TestScriptsSync(unittest.TestCase):
    def test_a_script_naming_only_a_video_in_either_folder_matches_nothing(self):
        with a_library() as lib:
            _flick_in(lib)
            _made_by_origenerator(lib)
            for name in ("loop_1", "video_1"):
                script = lib.scripts / "unfiled" / f"{name}.funscript"
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text("{}", encoding="utf-8")

            result = scripts_sync.run()

            self.assertEqual((result.unmatched, result.moved), (2, 0))
            self.assertFalse((lib.scripts / "genau").exists() or (lib.scripts / "origenerator").exists())


class TestCarvedClipScripts(CarvedClipLibraryCase):
    def _a_clip_in(self, folder_name: str, *, with_script: bool):
        scene = self.make_scene(actions=None if with_script else [
            {"at": 9_000, "pos": 0}, {"at": 10_500, "pos": 90}, {"at": 11_500, "pos": 10}])
        video = self.videos / folder_name / "clips" / "clip.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        record = self.metadata / folder_name / "clips" / "clip.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"clip": {"full_video": str(scene), "scene_offset": 10.0}}),
                          encoding="utf-8")
        if with_script:
            script = self.scripts / folder_name / "clips" / "clip.funscript"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(json.dumps({"actions": [{"at": 500, "pos": 90}, {"at": 1_500, "pos": 10}]}),
                              encoding="utf-8")
        return scene

    def _folders_inside_the_library(self):
        return override_config(GENAU_DIR=self.videos / "genau",
                               ORIGENERATOR_VIDEOS_DIR=self.videos / "origenerator")

    def test_a_clip_in_either_folder_is_given_no_script_cut_from_its_scene(self):
        for folder_name in ("genau", "origenerator"):
            with self.subTest(folder=folder_name):
                self._a_clip_in(folder_name, with_script=False)
                with self.library_overrides(), self._folders_inside_the_library(), \
                     patch.object(clip_scripts.ffprobe, "duration_seconds", return_value=2.0):
                    result = clip_scripts.run()

                self.assertEqual(result.written, 0)
                self.assertFalse((self.scripts / folder_name / "clips" / "clip.funscript").exists())

    def test_a_scene_is_given_no_script_from_a_clip_in_either_folder(self):
        for folder_name in ("genau", "origenerator"):
            with self.subTest(folder=folder_name):
                scene = self._a_clip_in(folder_name, with_script=True)
                with self.library_overrides(), self._folders_inside_the_library(), \
                     patch.object(scene_scripts.ffprobe, "duration_seconds", return_value=60.0):
                    result = scene_scripts.run()

                self.assertEqual(result.written, 0)
                self.assertFalse(self.scene_script(scene.stem).exists())


class TestFollowingVideosThatMoved(unittest.TestCase):
    def test_a_reference_is_followed_into_genau_s_folder_but_not_into_origenerator_s(self):
        with a_library() as lib:
            flick = _flick_in(lib)
            _made_by_origenerator(lib)
            index = video_locator.build_index()

            self.assertEqual(video_locator.relocate(Path("gone") / "loop_1.mp4", index), flick)
            self.assertIsNone(video_locator.relocate(Path("gone") / "video_1.mp4", index))


class TestTheMirrors(unittest.TestCase):
    def test_a_video_in_either_folder_has_no_script_in_the_library(self):
        with a_library() as lib:
            for video in (_flick_in(lib), _made_by_origenerator(lib)):
                with self.subTest(video=video.name), self.assertRaises(ValueError):
                    script_library.script_path_for_video(video)

    def test_genau_s_sidecars_stay_under_genau_in_the_metadata_tree(self):
        with a_library() as lib:
            self.assertEqual(sidecar.sidecar_path(_flick_in(lib)),
                             lib.metadata / "genau" / "flicks" / "2D" / "AI" / "loop_1.json")


if __name__ == "__main__":
    unittest.main()
