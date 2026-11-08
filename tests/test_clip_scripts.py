from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tasks import clip_scripts
from tests.temp_helpers import CarvedClipLibraryCase
from util import provenance, scene_links, sidecar


class ClipScriptsCase(CarvedClipLibraryCase):
    def run_stage(self, duration=2.0):
        with self.library_overrides(), \
             patch.object(clip_scripts.ffprobe, "duration_seconds", return_value=duration):
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

        assert result.written == 1
        written = json.loads(self.clip_script().read_text(encoding="utf-8"))
        assert written["actions"] == [{"at": 0, "pos": 0}, {"at": 500, "pos": 90}, {"at": 1500, "pos": 10}]

    def test_the_mark_that_this_stage_cut_a_script_is_in_the_script_never_on_the_clips_record(self):
        scene = self.make_scene(actions=[{"at": 10_000, "pos": 0}, {"at": 10_500, "pos": 90}])
        clip = self.make_clip(scene, scene_offset=10.0)

        self.run_stage(duration=2.0)

        written = json.loads(self.clip_script().read_text(encoding="utf-8"))
        stamp = written["metadata"][provenance.BLOCK][provenance.CLIP_SCRIPTS]
        assert (stamp["app"], stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("evolver", None, None)
        with self.library_overrides():
            assert set(sidecar.read(sidecar.sidecar_path(clip))) == {"clip"}

    def test_a_clip_script_carries_its_scene_scripts_stamp_for_a_sweep_to_find_it_by(self):
        placed = provenance.reconstructed("evolver")
        scene = self.make_scene()
        self.write_scene_script(
            scene, [{"at": 10_000, "pos": 0}, {"at": 10_500, "pos": 90}],
            metadata={provenance.BLOCK: {provenance.SCENE_SCRIPTS: placed}})
        self.make_clip(scene, scene_offset=10.0)

        self.run_stage(duration=2.0)

        stamps = json.loads(self.clip_script().read_text(encoding="utf-8"))["metadata"][provenance.BLOCK]
        assert set(stamps) == {provenance.SCENE_SCRIPTS, provenance.CLIP_SCRIPTS}
        assert stamps[provenance.SCENE_SCRIPTS] == placed

    def test_leaves_a_clip_alone_when_its_scene_has_no_script(self):
        scene = self.make_scene()
        self.make_clip(scene)

        result = self.run_stage()

        assert result.written == 0
        assert result.no_scene_script == 1
        assert not self.clip_script().exists()

    def test_never_overwrites_a_script_the_clip_already_has(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}])
        self.make_clip(scene)
        existing = self.clip_script()
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text('{"actions": [{"at": 7, "pos": 42}]}', encoding="utf-8")

        result = self.run_stage()

        assert result.written == 0
        assert result.already_scripted == 1
        assert json.loads(existing.read_text(encoding="utf-8"))["actions"] == [{"at": 7, "pos": 42}]

    def test_writes_nothing_when_the_clip_outlasts_the_scripted_motion(self):
        scene = self.make_scene(actions=[{"at": 1_000, "pos": 0}, {"at": 2_000, "pos": 90}])
        self.make_clip(scene, scene_offset=600.0)

        result = self.run_stage()

        assert result.written == 0
        assert result.no_motion_in_window == 1
        assert not self.clip_script().exists()

    def test_a_window_holding_a_single_position_leaves_the_clip_free_to_be_scripted_properly(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}])
        self.make_clip(scene, scene_offset=10.0)

        result = self.run_stage(duration=2.0)

        assert result.written == 0
        assert result.no_motion_in_window == 1
        assert not self.clip_script().exists()

    def test_skips_a_clip_whose_own_length_will_not_probe(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])
        self.make_clip(scene)

        result = self.run_stage(duration=None)

        assert result.written == 0
        assert result.unprobeable == 1
        assert not self.clip_script().exists()

    def test_passes_over_a_clip_not_yet_matched_to_its_scene(self):
        scene = self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])
        self.make_clip(scene, clip={"source": "Scene Three 9", "start": "27:46"})

        result = self.run_stage()

        assert result.written == 0
        assert result.unmatched_clip == 1
        assert not self.clip_script().exists()

    def test_ignores_a_video_that_was_never_carved_from_anything(self):
        self.make_scene(actions=[{"at": 10_500, "pos": 90}, {"at": 11_000, "pos": 10}])

        result = self.run_stage()

        assert result.written == 0
        assert result.unmatched_clip == 0


if __name__ == "__main__":
    unittest.main()


class TestAClipStillNamingItsSceneByPath(ClipScriptsCase):
    def test_is_moved_to_its_scenes_id_and_scripted_from_it(self):
        scene = self.make_scene(actions=[{"at": 10_000, "pos": 0}, {"at": 10_500, "pos": 90}])
        clip = self.make_clip(scene, clip={"full_video": str(scene), "scene_offset": 10.0})

        result = self.run_stage(duration=2.0)

        with self.library_overrides():
            assert sidecar.read(sidecar.sidecar_path(clip))["clip"] == {
                **scene_links.link_to(scene), "scene_offset": 10.0}
        assert result.written == 1
