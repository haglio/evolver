from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import config

# The system temp dir, not a directory inside the checkout: the suite must not
# write into the tree it is testing (a killed run left case directories in the
# repo, a read-only checkout could not run at all, and fixture paths were bound
# to wherever the repo happened to live, so a second worktree behaved
# differently from the primary one).
ROOT = Path(tempfile.gettempdir()) / "evolver-tests" / "unittest"


@contextmanager
def workspace_temp_dir():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        # ignore_errors stays for now: on Windows a file a media backend still
        # holds open makes rmtree raise, and whether any test leans on that
        # silence can only be proven on windows-latest, which the publication
        # freeze keeps out of reach. Dropping it is recorded in the changelog.
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def override_config(**overrides):
    """Temporarily override config module attributes with auto-restore."""
    with ExitStack() as stack:
        for key, value in overrides.items():
            stack.enter_context(patch.object(config, key, value))
        yield


class _LibraryTree:
    """Paths into one temp AI-library tree, plus builders for its files."""

    def __init__(self, root: Path):
        self.root = root
        self.ai = root / "AI"
        self.upscaled = self.ai / "2_outbox" / "upscaled_by_orientation"
        self.metadata = root / "metadata"
        self.weird = root / "kinda_weird"

    def video(self, orient="portrait", source="provider2", name="a_topaz.mp4") -> Path:
        video = self.upscaled / orient / source / name
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def sidecar(self, orient, source, stem, payload) -> Path:
        path = (self.metadata / "AI" / "2_outbox" / "upscaled_by_orientation"
                / orient / source / f"{stem}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


@contextmanager
def library_tree(**config_extra):
    """The AI-library temp tree and the config pointing at it, together.

    The layout is a real contract (config.py mirrors it, and genau and
    fun_time read the same shape); it used to be re-implemented by hand in
    four test files with 26 copies of the same four-key override_config line.
    Extra config keys (e.g. WEIRD_DIR) ride along per test.
    """
    with workspace_temp_dir() as root:
        tree = _LibraryTree(root)
        overrides = dict(
            VIDEO_LIBRARY_DIR=tree.root,
            AI_DIR=tree.ai,
            OUT_UPSCALED_DIR=tree.upscaled,
            METADATA_DIR=tree.metadata,
            WEIRD_DIR=tree.weird,
        )
        overrides.update(config_extra)
        with override_config(**overrides):
            yield tree


def make_video(path: Path) -> Path:
    """A file at *path* that every "is this a video" check will accept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def nonai_library_overrides(root: Path, **extra):
    """Config overrides mapping a temp tree shaped like the real non-AI library.

    METADATA_DIR belongs here with the rest: a sidecar's path is the metadata
    root joined to the video's path *within the library*, so pointing only the
    library at the temp tree sends every sidecar a test writes to whatever
    metadata root the checkout is configured with — the real one, on a machine
    that has a real one. Tests then also share that tree with each other, and
    two of them naming a clip the same way read back one another's fixtures.

    NONAI_RETIRED_ROOT and NONAI_PRIORITY_MANIFEST are here for the same
    reason, and both default to a machine's own answer rather than to nothing:
    the archive comes from the overlay's ``retired_root``, and the pin manifest
    is a path *inside the checkout*. So on a machine that has configured an
    archive, retiring an original in a test moved the fixture into the real one
    and then failed the assertion that it had gone to the bucket's ``2*``
    folder — four tests, green here and on CI only because neither has an
    overlay. Pinned to the case's own temp tree, they cannot.
    """
    video_lib = root / "videos"
    overrides = dict(
        VIDEO_LIBRARY_DIR=video_lib,
        # The sidecar mirror answers for a video under either root. Pinned to
        # the library itself rather than to its parent, so an archived original
        # a case parks beside the tree stays outside both, as the real archive
        # sits off the working drive.
        VIDEO_SEARCH_ROOT=video_lib,
        NON_AI_DIR=video_lib / "2D" / "non_AI",
        METADATA_DIR=root / "metadata",
        SCRIPT_LIBRARY_DIR=root / "scripts",
        NONAI_RETIRED_ROOT=None,
        NONAI_PRIORITY_MANIFEST=root / "next.txt",
        NONAI_SKIP_MANIFEST=root / "skip.txt",
        NONAI_JOB_STATE_FILE=root / "job.json",
        NONAI_ATTEMPTS_FILE=root / "attempts.json",
        NONAI_COOLDOWN_FILE=root / "cooldown.json",
        NONAI_FFMPEG_LOG=root / "ffmpeg.log",
        FUN_TIME_WATCH_STATS_FILE=root / "watch_stats.json",
    )
    overrides.update(extra)
    return overrides


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
        finished_at="2026-07-25T15:20:14",
        duration_seconds=12.0,
        trigger="scheduled",
        status="success",
        stages=[],
        log_start=None,
        log_end=None,
    )
    fields.update(overrides)
    return RunRecord(**fields)
