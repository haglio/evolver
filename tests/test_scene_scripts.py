from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tasks import scene_scripts
from tests.temp_helpers import LAGOON, CarvedClipLibraryCase
from util import provenance


class SceneScriptsCase(CarvedClipLibraryCase):
    def run_stage(self, duration=600.0):
        with self.library_overrides(), \
             patch.object(scene_scripts.ffprobe, "duration_seconds", return_value=duration):
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

        assert result.written == 1
        written = json.loads(self.scene_script().read_text(encoding="utf-8"))
        assert written["actions"] == [{"at": 493250, "pos": 60}, {"at": 494750, "pos": 10}, {"at": 534783, "pos": 48}]

    def test_a_placed_script_says_in_itself_that_this_stage_placed_it(self):
        scene = self.make_scene()
        self.make_clip(scene, scene_offset=300.0, actions=[{"at": 0, "pos": 0}, {"at": 900, "pos": 90}])

        self.run_stage()

        written = json.loads(self.scene_script().read_text(encoding="utf-8"))
        stamp = written["metadata"][provenance.BLOCK][provenance.SCENE_SCRIPTS]
        assert (stamp["app"], stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("evolver", None, None)

    def test_the_rest_of_the_scene_is_left_unscripted(self):
        scene = self.make_scene()
        self.make_clip(scene, scene_offset=300.0, actions=[{"at": 0, "pos": 0}, {"at": 900, "pos": 90}])

        self.run_stage(duration=3_600.0)

        written = json.loads(self.scene_script().read_text(encoding="utf-8"))
        assert [action["at"] for action in written["actions"]] == [300000, 300900]

    def test_never_overwrites_a_script_the_scene_already_has(self):
        scene = self.make_scene(actions=[{"at": 7, "pos": 42}])
        self.make_clip(scene, actions=[{"at": 0, "pos": 90}])

        result = self.run_stage()

        assert result.written == 0
        assert result.already_scripted == 1
        assert json.loads(self.scene_script().read_text(encoding="utf-8"))["actions"] == [{"at": 7, "pos": 42}]

    def test_leaves_a_scene_alone_when_its_clip_has_no_script(self):
        scene = self.make_scene()
        self.make_clip(scene)

        result = self.run_stage()

        assert result.written == 0
        assert result.no_clip_script == 1
        assert not self.scene_script().exists()

    def test_skips_a_clip_the_matcher_has_not_placed_yet(self):
        video = self.videos / LAGOON / "clips" / "unmatched.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / LAGOON / "clips" / "unmatched.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps({"clip": {"compilation": "Vol1", "index": 3}}), encoding="utf-8")

        result = self.run_stage()

        assert result.written == 0
        assert result.unmatched_clip == 1

    def test_skips_a_scene_that_has_left_the_library(self):
        gone = self.videos / LAGOON / "scenes" / "moved-away.mp4"
        self.make_clip(gone, actions=[{"at": 0, "pos": 90}])

        result = self.run_stage()

        assert result.written == 0
        assert result.scene_gone == 1

    def test_a_whole_video_that_is_not_a_clip_is_not_a_source(self):
        plain = self.videos / LAGOON / "scenes" / "ordinary.mp4"
        plain.parent.mkdir(parents=True, exist_ok=True)
        plain.write_bytes(b"scene")

        result = self.run_stage()

        assert result.written == 0
        assert result.unmatched_clip == 0


if __name__ == "__main__":
    unittest.main()
