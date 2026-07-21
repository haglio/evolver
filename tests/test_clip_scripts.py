import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import clip_scripts
from tests.temp_helpers import override_config, workspace_temp_dir


WINSTON = Path("2D") / "non_AI" / "winston"


class ClipScriptsCase(unittest.TestCase):
    """A carved clip, its source scene, and the scene's script, in a temp library."""

    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.videos = self.root / "videos"
        self.scripts = self.root / "scripts"
        self.metadata = self.root / "metadata"

    def make_scene(self, name="scene", actions=None):
        scene = self.videos / WINSTON / "scenes" / f"{name}.mp4"
        scene.parent.mkdir(parents=True, exist_ok=True)
        scene.write_bytes(b"scene")
        if actions is not None:
            self.write_scene_script(scene, actions)
        return scene

    def write_scene_script(self, scene, actions, **extra):
        script = self.scripts / WINSTON / "scenes" / f"{scene.stem}.funscript"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps({"actions": actions, **extra}), encoding="utf-8")
        return script

    def make_clip(self, scene, name="clip", scene_offset=10.0, clip=None):
        video = self.videos / WINSTON / "clips" / f"{name}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / WINSTON / "clips" / f"{name}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        payload = {"clip": {"full_video": str(scene), "scene_offset": scene_offset}}
        if clip is not None:
            payload["clip"] = clip
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        return video

    def clip_script(self, name="clip"):
        return self.scripts / WINSTON / "clips" / f"{name}.funscript"

    def run_stage(self, duration=2.0):
        with override_config(
            VIDEO_LIBRARY_DIR=self.videos,
            SCRIPT_LIBRARY_DIR=self.scripts,
            METADATA_DIR=self.metadata,
        ), patch.object(clip_scripts.ffprobe, "duration_seconds", return_value=duration):
            return clip_scripts.run()


class TestClipScripts(ClipScriptsCase):
    def test_writes_the_scene_script_trimmed_to_the_clip(self):
        scene = self.make_scene(actions=[
            {"at": 9_000, "pos": 0},
            {"at": 10_500, "pos": 90},
            {"at": 11_500, "pos": 10},
            {"at": 30_000, "pos": 50},
        ])
        self.make_clip(scene, scene_offset=10.0)

        result = self.run_stage(duration=2.0)

        self.assertEqual(result.written, 1)
        written = json.loads(self.clip_script().read_text(encoding="utf-8"))
        self.assertEqual(
            written["actions"],
            [{"at": 0, "pos": 0}, {"at": 500, "pos": 90}, {"at": 1_500, "pos": 10}],
        )

    def test_leaves_a_clip_alone_when_its_scene_has_no_script(self):
        scene = self.make_scene()
        self.make_clip(scene)

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.no_scene_script, 1)
        self.assertFalse(self.clip_script().exists())

    def test_never_overwrites_a_script_the_clip_already_has(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}])
        self.make_clip(scene)
        existing = self.clip_script()
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text('{"actions": [{"at": 7, "pos": 42}]}', encoding="utf-8")

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.already_scripted, 1)
        self.assertEqual(
            json.loads(existing.read_text(encoding="utf-8"))["actions"],
            [{"at": 7, "pos": 42}],
        )

    def test_writes_nothing_when_the_clip_outlasts_the_scripted_motion(self):
        scene = self.make_scene(actions=[{"at": 1_000, "pos": 0}, {"at": 2_000, "pos": 90}])
        self.make_clip(scene, scene_offset=600.0)

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.no_motion_in_window, 1)
        self.assertFalse(self.clip_script().exists())

    def test_skips_a_clip_whose_duration_will_not_probe(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])
        self.make_clip(scene)

        result = self.run_stage(duration=None)

        self.assertEqual(result.written, 0)
        self.assertEqual(result.unprobeable, 1)
        self.assertFalse(self.clip_script().exists())

    def test_passes_over_a_clip_not_yet_matched_to_its_scene(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])
        self.make_clip(scene, clip={"source": "Scene Three 9", "start": "27:46"})

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.unmatched_clip, 1)
        self.assertFalse(self.clip_script().exists())

    def test_ignores_a_video_that_was_never_carved_from_anything(self):
        self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.unmatched_clip, 0)


if __name__ == "__main__":
    unittest.main()
