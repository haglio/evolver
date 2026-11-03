from __future__ import annotations

import json
import shutil
import sqlite3
import string
import tempfile
import time
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from app_support.flick_folder import flat_flicks_in

import config
from gui.run_record import RunRecord
from util import nonai_job, provenance
from util.media_files import partial_path

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
    with ExitStack() as stack:
        for key, value in overrides.items():
            stack.enter_context(patch.object(config, key, value))
        yield


class _LibraryTree:
    def __init__(self, root: Path):
        self.root = root
        self.ai = root / "AI"
        self.upscaled = self.ai / "2_outbox" / "upscaled_by_orientation"
        self.metadata = root / "metadata"
        self.trash = root / "trash"

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


def a_drive_that_is_not_there() -> Path:
    return next(drive for drive in (Path(f"{letter}:/") for letter in reversed(string.ascii_uppercase))
                if not drive.exists())


def write_sidecar(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


@contextmanager
def library_tree(**config_extra):
    with workspace_temp_dir() as root:
        tree = _LibraryTree(root)
        overrides = dict(
            VIDEO_LIBRARY_DIR=tree.root,
            AI_DIR=tree.ai,
            OUT_UPSCALED_DIR=tree.upscaled,
            METADATA_DIR=tree.metadata,
            TRASH_DIR=tree.trash,
        )
        overrides.update(config_extra)
        with override_config(**overrides):
            yield tree


class LaneLibrary:
    def __init__(self, root: Path):
        videos = root / "videos"
        self.library = videos / "videos"
        self.ai = self.library / "2D" / "AI"
        self.inbox = self.ai / "0_inbox"
        self.sorted_dir = self.ai / "1_sorted"
        self.outbox = self.ai / "2_outbox" / "upscaled_by_orientation"
        self.non_ai = self.library / "2D" / "non_AI"
        self.trash = self.ai / "2_outbox" / "trash"
        self.genau = self.library / "genau"
        self.genau_flicks = self.genau / "flicks"
        self.genau_trash = self.genau / "trash"
        self.genau_audio = videos / "audio" / "genau"
        self.origenerator = self.library / "origenerator"
        self.metadata = videos / "metadata"
        self.scripts = videos / "scripts" / "scripts"
        self.unmatched = videos / "scripts" / "unmatched_scripts"
        self.generated = videos / "scripts" / "generated"
        self.search_root = videos

    def config(self, genau_source="example-loop-clips", **extra):
        settings = {
            "VIDEO_LIBRARY_DIR": self.library, "VIDEO_SEARCH_ROOT": self.search_root,
            "METADATA_DIR": self.metadata, "INBOX_DIR": self.inbox,
            "SCRIPT_LIBRARY_DIR": self.scripts, "UNMATCHED_SCRIPTS_DIR": self.unmatched,
            "GENERATED_SCRIPTS_DIR": self.generated,
            "SORTED_DIR": self.sorted_dir,
            "OUT_UPSCALED_DIR": self.outbox, "NON_AI_DIR": self.non_ai,
            "TRASH_DIR": self.trash,
            "GENAU_DIR": self.genau, "GENAU_SOURCE": genau_source,
            "ORIGENERATOR_VIDEOS_DIR": self.origenerator,
            "GENAU_TRASH_DIR": self.genau_trash, "GENAU_AUDIO_DIR": self.genau_audio,
            "CLIP_FOLDERS": (), "VR_VIDEO_DIR": None,
        }
        settings.update(extra)
        flat_flicks_in(self.genau_flicks).mkdir(parents=True, exist_ok=True)
        return override_config(**settings)


def gallery_of_videos_made_again(path: Path, names) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE generations (prompt_id TEXT, output_files TEXT, remade_at TEXT)")
    for number, name in enumerate(names):
        conn.execute("INSERT INTO generations VALUES (?, ?, '2026-01-02 03:04:05')",
                     (f"made-{number}", json.dumps([{"filename": name, "subfolder": "video"}])))
    conn.commit()
    conn.close()
    return path


def touch_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def make_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


STARTED_UNDER = provenance.reconstructed("evolver", method="non_ai_upscale",
                                         method_version="v000")


def write_job(root, overrides, *, pid=4242, started_seconds_ago=60.0, expected=100.0,
              source=None, tmp_bytes=b"partial", suspended=False, suspended_at=0.0,
              suspended_seconds=0.0, job_file=None, stamp=STARTED_UNDER,
              on_request=False):
    non_ai = overrides["NON_AI_DIR"]
    source = source or make_video(non_ai / "lagoon" / "0 unsorted" / "busy.mp4")
    out = non_ai / "lagoon" / "3_good_to_go" / "processed" / f"{source.stem}_apo8_iris2.mp4"
    tmp = partial_path(out, source.stem)
    if tmp_bytes is not None:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(tmp_bytes)
    job = {
        "pid": pid,
        "source": str(source),
        "tmp": str(tmp),
        "out": str(out),
        "expected_duration": expected,
        "started_at": time.time() - started_seconds_ago,
        "suspended": suspended,
        "suspended_at": suspended_at,
        "suspended_seconds": suspended_seconds,
    }
    if stamp is not None:
        job["provenance"] = stamp
    if on_request:
        job["on_request"] = True
    job_file = job_file or overrides["NONAI_JOB_STATE_FILE"]
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps(job), encoding="utf-8")
    return source, tmp, out


def nonai_library_overrides(root: Path, **extra):
    video_lib = root / "videos"
    overrides = dict(
        VIDEO_LIBRARY_DIR=video_lib,
        VIDEO_SEARCH_ROOT=video_lib,
        NON_AI_DIR=video_lib / "2D" / "non_AI",
        METADATA_DIR=root / "metadata",
        SCRIPT_LIBRARY_DIR=root / "scripts",
        GENERATED_SCRIPTS_DIR=root / "generated",
        NONAI_RETIRED_ROOT=None,
        NONAI_PIN_LIST=root / "next.txt",
        NONAI_SKIP_LIST=root / "skip.txt",
        NONAI_JOB_STATE_FILE=root / "job.json",
        NONAI_ATTEMPTS_FILE=root / "attempts.json",
        NONAI_COOLDOWN_FILE=root / "cooldown.json",
        NONAI_REQUEST_FILE=root / "request.json",
        NONAI_FFMPEG_LOG=root / "ffmpeg.log",
        FUN_TIME_WATCH_STATS_FILE=root / "watch_stats.json",
    )
    overrides.update(extra)
    return overrides


LAGOON = Path("2D") / "non_AI" / "lagoon"


class CarvedClipLibraryCase(unittest.TestCase):
    def setUp(self):
        self._workspace = workspace_temp_dir()
        self.root = self._workspace.__enter__()
        self.addCleanup(self._workspace.__exit__, None, None, None)
        self.videos = self.root / "videos"
        self.scripts = self.root / "scripts"
        self.metadata = self.root / "metadata"

    def make_scene(self, name="scene", actions=None):
        scene = self.videos / LAGOON / "scenes" / f"{name}.mp4"
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
        video = self.videos / LAGOON / "clips" / f"{name}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"clip")
        sidecar = self.metadata / LAGOON / "clips" / f"{name}.json"
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
        return self.scripts / LAGOON / "scenes" / f"{name}.funscript"

    def clip_script(self, name="clip"):
        return self.scripts / LAGOON / "clips" / f"{name}.funscript"

    def library_overrides(self):
        return override_config(
            VIDEO_LIBRARY_DIR=self.videos,
            SCRIPT_LIBRARY_DIR=self.scripts,
            METADATA_DIR=self.metadata,
        )


def make_run_record(**overrides):
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


def probes(videoai="", orientation="landscape", duration=100.0, free_bytes=10**15,
           popen=None, is_running=True, image="ffmpeg.exe", terminate=True,
           topaz_pids=(), cmdline=None, available_ram=64.0, idle_seconds=10_000.0):
    stack = ExitStack()
    mocks = {
        "idle_seconds": stack.enter_context(
            patch("tasks.nonai_encode.seconds_since_input",
                  return_value=idle_seconds)),
        "suspend": stack.enter_context(
            patch("util.processes.suspend", return_value=True)),
        "resume": stack.enter_context(
            patch("util.processes.resume", return_value=True)),
        "videoai": stack.enter_context(
            patch("util.ffprobe.videoai_tag", return_value=videoai)),
        "orientation": stack.enter_context(
            patch("util.ffprobe.orientation_of", return_value=orientation)),
        "duration": stack.enter_context(
            patch("util.ffprobe.duration_seconds", return_value=duration)),
        "free_bytes": stack.enter_context(
            patch("util.system_resources.free_bytes", return_value=free_bytes)),
        "available_ram": stack.enter_context(
            patch("util.system_resources.available_ram_gb", return_value=available_ram)),
        "popen": stack.enter_context(
            patch("subprocess.Popen", popen or Mock(return_value=Mock(pid=4242)))),
        "is_running": stack.enter_context(
            patch("util.processes.is_running", return_value=is_running)),
        "image_path": stack.enter_context(
            patch("util.processes.image_path", return_value=image)),
        "terminate": stack.enter_context(
            patch("util.processes.terminate", return_value=terminate)),
        "pids_of_image": stack.enter_context(
            patch("util.processes.pids_of_image", return_value=list(topaz_pids))),
        "command_line": stack.enter_context(
            patch("util.processes.command_line", return_value=cmdline)),
        "sign_in_expired": stack.enter_context(
            patch("util.topaz.sign_in_expired", return_value=False)),
    }
    return stack, mocks


def ask_for(overrides, video):
    nonai_job.save_request(overrides["NONAI_REQUEST_FILE"], nonai_job.Request(video))


def request_of(overrides):
    return nonai_job.load_request(overrides["NONAI_REQUEST_FILE"])
