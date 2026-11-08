from __future__ import annotations

import unittest
from pathlib import Path

import pytest

from tests.temp_helpers import override_config, workspace_temp_dir
from util import script_library


class TestTrim(unittest.TestCase):
    def test_keeps_actions_inside_the_window_rebased_to_zero(self):
        script = {
            "actions": [
                {"at": 5_000, "pos": 10},
                {"at": 10_000, "pos": 20},
                {"at": 11_000, "pos": 80},
                {"at": 12_000, "pos": 30},
                {"at": 20_000, "pos": 90},
            ],
        }

        trimmed = script_library.trim(script, start_seconds=10.0, duration_seconds=2.0)

        assert trimmed["actions"] == [{"at": 0, "pos": 20}, {"at": 1000, "pos": 80}, {"at": 2000, "pos": 30}]

    def test_carries_the_preceding_action_to_zero_so_the_device_does_not_lurch_at_the_clips_first_motion(self):
        script = {
            "actions": [
                {"at": 9_400, "pos": 15},
                {"at": 10_500, "pos": 80},
                {"at": 11_000, "pos": 30},
            ],
        }

        trimmed = script_library.trim(script, start_seconds=10.0, duration_seconds=2.0)

        assert trimmed["actions"] == [{"at": 0, "pos": 15}, {"at": 500, "pos": 80}, {"at": 1000, "pos": 30}]

    def test_keeps_the_scene_fields_but_redates_the_duration_to_the_clip(self):
        script = {
            "actions": [{"at": 10_000, "pos": 20}],
            "inverted": False,
            "range": 90,
            "version": "1.0",
            "metadata": {"creator": "someone", "type": "basic", "duration": 1402},
        }

        trimmed = script_library.trim(script, start_seconds=10.0, duration_seconds=126.5)

        assert not trimmed["inverted"]
        assert trimmed["range"] == 90
        assert trimmed["version"] == "1.0"
        assert trimmed["metadata"]["creator"] == "someone"
        assert trimmed["metadata"]["type"] == "basic"
        assert trimmed["metadata"]["duration"] == 126
        assert script["metadata"]["duration"] == 1402, "must not mutate the scene's script"

    def test_drops_annotations_whose_times_belong_to_the_scene(self):
        script = {
            "actions": [{"at": 10_000, "pos": 20}],
            "metadata": {
                "bookmarks": [{"name": "", "time": "00:25:54.503"}],
                "chapters": [{"name": "Beta", "startTime": "00:06:28.266", "endTime": "00:14:58.666"}],
                "title": "kept",
            },
        }

        trimmed = script_library.trim(script, start_seconds=10.0, duration_seconds=2.0)

        assert trimmed["metadata"]["bookmarks"] == []
        assert trimmed["metadata"]["chapters"] == []
        assert trimmed["metadata"]["title"] == "kept"


class TestScriptPathForVideo(unittest.TestCase):
    def test_mirrors_the_video_path_into_the_script_tree(self):
        videos = Path("C:/lib/videos")
        scripts = Path("C:/lib/scripts")

        with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
            path = script_library.script_path_for_video(videos / "2D" / "non_AI" / "lagoon" / "clip.mkv")

        assert path == scripts / "2D" / "non_AI" / "lagoon" / "clip.funscript"


class TestPlace(unittest.TestCase):
    def test_moves_every_action_to_where_the_clip_sits_and_scripts_nothing_else_so_the_device_stays_still_there(self):
        script = {"actions": [{"at": 500, "pos": 80}, {"at": 0, "pos": 15}]}

        placed = script_library.place(script, start_seconds=10.0, duration_seconds=126.5)

        assert placed["actions"] == [{"at": 10_000, "pos": 15}, {"at": 10_500, "pos": 80}]

    def test_redates_the_duration_and_drops_annotations_to_the_scene(self):
        script = {
            "actions": [],
            "metadata": {"duration": 3, "bookmarks": [{"name": "", "time": "00:00:01.000"}], "title": "kept"},
        }

        placed = script_library.place(script, start_seconds=10.0, duration_seconds=1402.9)

        assert placed["metadata"] == {"duration": 1402, "bookmarks": [], "title": "kept"}
        assert script["metadata"]["duration"] == 3, "must not mutate the clip's script"


class TestScriptPathOutsideTheLibrary(unittest.TestCase):
    def test_a_video_outside_the_library_like_an_archived_original_that_keeps_its_own_beside_it_has_no_script_here(self):
        with (
            override_config(VIDEO_LIBRARY_DIR=Path("C:/lib/videos"), SCRIPT_LIBRARY_DIR=Path("C:/lib/scripts")),
            pytest.raises(ValueError, match="not in the video library"),
        ):
            script_library.script_path_for_video(Path("C:/archive/clip.mkv"))


class TestTheMarkSayingNoPersonWroteAScript(unittest.TestCase):
    def _library(self, root):
        return override_config(
            VIDEO_LIBRARY_DIR=root / "videos",
            SCRIPT_LIBRARY_DIR=root / "scripts",
            GENERATED_SCRIPTS_DIR=root / "marks",
        )

    def test_a_copied_script_keeps_the_mark_its_original_had(self):
        with workspace_temp_dir() as root, self._library(root):
            original = root / "scripts" / "a" / "clip.funscript"
            original.parent.mkdir(parents=True)
            original.write_text("{}", encoding="utf-8")
            script_library.mark_generated(original)
            copy = root / "scripts" / "b" / "clip.funscript"

            script_library.copy_script(original, copy)

            assert script_library.is_marked_generated(copy)

    def test_a_copy_of_a_script_a_person_wrote_is_not_marked(self):
        with workspace_temp_dir() as root, self._library(root):
            original = root / "scripts" / "a" / "clip.funscript"
            original.parent.mkdir(parents=True)
            original.write_text("{}", encoding="utf-8")
            copy = root / "scripts" / "b" / "clip.funscript"

            script_library.copy_script(original, copy)

            assert not script_library.is_marked_generated(copy)

    def test_deleting_a_script_deletes_its_mark_too(self):
        with workspace_temp_dir() as root, self._library(root):
            script = root / "scripts" / "clip.funscript"
            script.parent.mkdir(parents=True)
            script.write_text("{}", encoding="utf-8")
            script_library.mark_generated(script)

            script_library.delete_script(script)

            assert not script_library.is_marked_generated(script)


class TestStampingAScript:
    def test_the_script_given_is_not_written_on(self):
        script = {"actions": [], "metadata": {"title": "scene one"}}

        script_library.stamped_in_its_own_metadata(script, "trim")

        assert script == {"actions": [], "metadata": {"title": "scene one"}}

    def test_a_script_with_no_metadata_gets_the_stamp_alone(self):
        stamped = script_library.stamped_in_its_own_metadata({"actions": []}, "trim")

        assert list(stamped["metadata"]["provenance"]) == ["trim"]


if __name__ == "__main__":
    unittest.main()
