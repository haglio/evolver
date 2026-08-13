import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import scene_scripts
from tests.temp_helpers import override_config, workspace_temp_dir


LARKIN = Path("2D") / "non_AI" / "larkin"


class SceneScriptsCase(unittest.TestCase):
    """A carved clip with a script, and the scene it came out of, in a temp library."""

    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.videos = self.root / "videos"
        self.scripts = self.root / "scripts"
        self.metadata = self.root / "metadata"

    def make_scene(self, name="scene", actions=None):
        scene = self.videos / LARKIN / "scenes" / f"{name}.mp4"
        scene.parent.mkdir(parents=True, exist_ok=True)
        scene.write_bytes(b"scene")
        if actions is not None:
            script = self.scene_script(name)
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(json.dumps({"actions": actions}), encoding="utf-8")
        return scene

    def make_clip(self, scene, name="clip", scene_offset=10.0, actions=None, **extra):
        video = self.videos / LARKIN / "clips" / f"{name}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / LARKIN / "clips" / f"{name}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        clip = {"full_video": str(scene), "scene_offset": scene_offset}
        clip.update(extra)
        sidecar.write_text(json.dumps({"clip": clip}), encoding="utf-8")
        if actions is not None:
            script = self.scripts / LARKIN / "clips" / f"{name}.funscript"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(json.dumps({"actions": actions}), encoding="utf-8")
        return video

    def scene_script(self, name="scene"):
        return self.scripts / LARKIN / "scenes" / f"{name}.funscript"

    def run_stage(self, duration=600.0):
        with override_config(
            VIDEO_LIBRARY_DIR=self.videos,
            SCRIPT_LIBRARY_DIR=self.scripts,
            METADATA_DIR=self.metadata,
        ), patch.object(scene_scripts.ffprobe, "duration_seconds", return_value=duration):
            return scene_scripts.run()


class TestSceneScripts(SceneScriptsCase):
    def test_writes_the_clip_script_where_the_clip_sits_in_the_scene(self):
        scene = self.make_scene()
        self.make_clip(scene, scene_offset=493.25, actions=[
            {"at": 0, "pos": 60},
            {"at": 1_500, "pos": 10},
            {"at": 41_533, "pos": 48},
        ])

        result = self.run_stage()

        self.assertEqual(result.written, 1)
        written = json.loads(self.scene_script().read_text(encoding="utf-8"))
        self.assertEqual(
            written["actions"],
            [
                {"at": 493_250, "pos": 60},
                {"at": 494_750, "pos": 10},
                {"at": 534_783, "pos": 48},
            ],
        )

    def test_the_rest_of_the_scene_is_left_unscripted(self):
        """A scene runs for an hour and the clip covers a minute of it. Nothing
        is invented for the rest: silence leaves the device still, which is the
        truth about a stretch nobody has scripted."""
        scene = self.make_scene()
        self.make_clip(scene, scene_offset=300.0, actions=[{"at": 0, "pos": 0}, {"at": 900, "pos": 90}])

        self.run_stage(duration=3_600.0)

        written = json.loads(self.scene_script().read_text(encoding="utf-8"))
        self.assertEqual([action["at"] for action in written["actions"]], [300_000, 300_900])

    def test_never_overwrites_a_script_the_scene_already_has(self):
        scene = self.make_scene(actions=[{"at": 7, "pos": 42}])
        self.make_clip(scene, actions=[{"at": 0, "pos": 90}])

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.already_scripted, 1)
        self.assertEqual(
            json.loads(self.scene_script().read_text(encoding="utf-8"))["actions"],
            [{"at": 7, "pos": 42}],
        )

    def test_leaves_a_scene_alone_when_its_clip_has_no_script(self):
        scene = self.make_scene()
        self.make_clip(scene)

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.no_clip_script, 1)
        self.assertFalse(self.scene_script().exists())

    def test_skips_a_clip_the_matcher_has_not_placed_yet(self):
        """Most clips have no ``full_video``: the scene they were cut from is
        not in the library at all, and nothing here can guess it."""
        video = self.videos / LARKIN / "clips" / "unmatched.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / LARKIN / "clips" / "unmatched.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps({"clip": {"compilation": "Vol1", "index": 3}}), encoding="utf-8")

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.unmatched_clip, 1)

    def test_skips_a_scene_that_has_left_the_library(self):
        """A recorded match names a file that can since have been renamed,
        archived or deleted; writing its script would only litter the tree."""
        gone = self.videos / LARKIN / "scenes" / "moved-away.mp4"
        self.make_clip(gone, actions=[{"at": 0, "pos": 90}])

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.scene_gone, 1)

    def test_a_whole_video_that_is_not_a_clip_is_not_a_source(self):
        """Only a carved clip carries the record; an ordinary video has no
        sidecar ``clip`` object and is never read as one."""
        plain = self.videos / LARKIN / "scenes" / "ordinary.mp4"
        plain.parent.mkdir(parents=True, exist_ok=True)
        plain.write_bytes(b"scene")

        result = self.run_stage()

        self.assertEqual(result.written, 0)
        self.assertEqual(result.unmatched_clip, 0)


if __name__ == "__main__":
    unittest.main()
