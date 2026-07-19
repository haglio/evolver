import unittest
from pathlib import Path

from util import funscript
from tests.temp_helpers import override_config


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

        trimmed = funscript.trim(script, start_seconds=10.0, duration_seconds=2.0)

        self.assertEqual(
            trimmed["actions"],
            [{"at": 0, "pos": 20}, {"at": 1_000, "pos": 80}, {"at": 2_000, "pos": 30}],
        )

    def test_carries_the_preceding_action_to_zero_so_t0_has_a_position(self):
        script = {
            "actions": [
                {"at": 9_400, "pos": 15},
                {"at": 10_500, "pos": 80},
                {"at": 11_000, "pos": 30},
            ],
        }

        trimmed = funscript.trim(script, start_seconds=10.0, duration_seconds=2.0)

        self.assertEqual(
            trimmed["actions"],
            [{"at": 0, "pos": 15}, {"at": 500, "pos": 80}, {"at": 1_000, "pos": 30}],
        )

    def test_keeps_the_scene_fields_but_redates_the_duration_to_the_clip(self):
        script = {
            "actions": [{"at": 10_000, "pos": 20}],
            "inverted": False,
            "range": 90,
            "version": "1.0",
            "metadata": {"creator": "someone", "type": "basic", "duration": 1402},
        }

        trimmed = funscript.trim(script, start_seconds=10.0, duration_seconds=126.5)

        self.assertFalse(trimmed["inverted"])
        self.assertEqual(trimmed["range"], 90)
        self.assertEqual(trimmed["version"], "1.0")
        self.assertEqual(trimmed["metadata"]["creator"], "someone")
        self.assertEqual(trimmed["metadata"]["type"], "basic")
        self.assertEqual(trimmed["metadata"]["duration"], 126)
        self.assertEqual(script["metadata"]["duration"], 1402, "must not mutate the scene's script")

    def test_drops_annotations_whose_times_belong_to_the_scene(self):
        script = {
            "actions": [{"at": 10_000, "pos": 20}],
            "metadata": {
                "bookmarks": [{"name": "", "time": "00:25:54.503"}],
                "chapters": [{"name": "Beta", "startTime": "00:06:28.266", "endTime": "00:14:58.666"}],
                "title": "kept",
            },
        }

        trimmed = funscript.trim(script, start_seconds=10.0, duration_seconds=2.0)

        self.assertEqual(trimmed["metadata"]["bookmarks"], [])
        self.assertEqual(trimmed["metadata"]["chapters"], [])
        self.assertEqual(trimmed["metadata"]["title"], "kept")


class TestScriptPathForVideo(unittest.TestCase):
    def test_mirrors_the_video_path_into_the_script_tree(self):
        videos = Path("C:/lib/videos")
        scripts = Path("C:/lib/scripts")

        with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
            path = funscript.script_path_for_video(videos / "2D" / "non_AI" / "larkin" / "clip.mkv")

        self.assertEqual(path, scripts / "2D" / "non_AI" / "larkin" / "clip.funscript")


if __name__ == "__main__":
    unittest.main()
