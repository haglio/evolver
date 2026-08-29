from __future__ import annotations

import json
import shutil
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import config


ROOT = Path(__file__).resolve().parent.parent / ".tmp-test" / "unittest"


@contextmanager
def workspace_temp_dir():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def override_config(**overrides):
    """Temporarily override config module attributes with auto-restore."""
    with ExitStack() as stack:
        for key, value in overrides.items():
            stack.enter_context(patch.object(config, key, value))
        yield


LARKIN = Path("2D") / "non_AI" / "larkin"


class CarvedClipLibraryCase(unittest.TestCase):
    """A carved clip, its source scene, and their scripts, in a temp library.

    The shared half of the clip_scripts and scene_scripts fixtures: the two
    stages carry a funscript between a clip and its scene in opposite
    directions, so the tree is one shape with the script on either end. Each
    test file used to carry its own byte-near-identical copy of this class.
    """

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
            self.write_scene_script(scene, actions)
        return scene

    def write_scene_script(self, scene, actions, **extra):
        script = self.scene_script(scene.stem)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps({"actions": actions, **extra}), encoding="utf-8")
        return script

    def make_clip(self, scene, name="clip", scene_offset=10.0, clip=None, actions=None):
        video = self.videos / LARKIN / "clips" / f"{name}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / LARKIN / "clips" / f"{name}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        if clip is None:
            clip = {"full_video": str(scene), "scene_offset": scene_offset}
        sidecar.write_text(json.dumps({"clip": clip}), encoding="utf-8")
        if actions is not None:
            script = self.clip_script(name)
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(json.dumps({"actions": actions}), encoding="utf-8")
        return video

    def scene_script(self, name="scene"):
        return self.scripts / LARKIN / "scenes" / f"{name}.funscript"

    def clip_script(self, name="clip"):
        return self.scripts / LARKIN / "clips" / f"{name}.funscript"

    def library_overrides(self):
        return override_config(
            VIDEO_LIBRARY_DIR=self.videos,
            SCRIPT_LIBRARY_DIR=self.scripts,
            METADATA_DIR=self.metadata,
        )


def make_run_record(**overrides):
    """A RunRecord with every field defaulted to an invented value.

    Five test classes each built the same seven fields by hand, three of
    them repeating identical literal timestamps -- so adding a RunRecord
    field meant editing five places. All values are fabricated, per this
    repo's fixture rule.
    """
    from gui.run_record import RunRecord

    fields = dict(
        id="2026-07-25T15-20-02",
        started_at="2026-07-25T15:20:02",
        finished_at="2026-07-25T15:20:02",
        duration_seconds=12.0,
        trigger="scheduled",
        status="success",
        stages=[],
    )
    fields.update(overrides)
    return RunRecord(**fields)
