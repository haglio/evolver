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

from app_support import processes
from app_support.flick_folder import flat_flicks_in
from app_support.testing import (
    process_alive,
    process_exe,
    process_resumed,
    process_suspended,
    process_terminated,
    processes_listed,
)

import config
from gui.run_record import RunRecord
from util import nonai_job, provenance
from util.media_files import partial_path

CASES_OUTSIDE_THE_CHECKOUT = Path(tempfile.gettempdir()) / "evolver-tests" / "unittest"


@contextmanager
def workspace_temp_dir():
    CASES_OUTSIDE_THE_CHECKOUT.mkdir(parents=True, exist_ok=True)
    path = CASES_OUTSIDE_THE_CHECKOUT / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        # Windows raises on a file a media backend holds open.
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def override_config(**overrides):
    with ExitStack() as stack:
        for key, value in overrides.items():
            stack.enter_context(patch.object(config, key, value))
        yield


def a_drive_that_is_not_there() -> Path:
    return next(drive for drive in (Path(f"{letter}:/") for letter in reversed(string.ascii_uppercase))
                if not drive.exists())


def write_sidecar(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


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


_JOB_DEFAULTS = {
    "pid": 4242, "started_seconds_ago": 60.0, "expected": 100.0, "source": None,
    "tmp_bytes": b"partial", "suspended": False, "suspended_at": 0.0,
    "suspended_seconds": 0.0, "job_file": None, "stamp": STARTED_UNDER, "on_request": False,
}


def _given_over(defaults, given):
    unknown = given.keys() - defaults.keys()
    if unknown:
        raise TypeError(f"unknown option: {', '.join(sorted(unknown))}")
    return {**defaults, **given}


def write_job(root, overrides, **given):
    options = _given_over(_JOB_DEFAULTS, given)
    non_ai = overrides["NON_AI_DIR"]
    source = options["source"] or make_video(non_ai / "lagoon" / "0 unsorted" / "busy.mp4")
    out = non_ai / "lagoon" / "3_good_to_go" / "processed" / f"{source.stem}_apo8_iris2.mp4"
    tmp = partial_path(out, source.stem)
    if options["tmp_bytes"] is not None:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(options["tmp_bytes"])
    job = {
        "pid": options["pid"],
        "source": str(source),
        "tmp": str(tmp),
        "out": str(out),
        "expected_duration": options["expected"],
        "started_at": time.time() - options["started_seconds_ago"],
        "suspended": options["suspended"],
        "suspended_at": options["suspended_at"],
        "suspended_seconds": options["suspended_seconds"],
    }
    if options["stamp"] is not None:
        job["provenance"] = options["stamp"]
    if options["on_request"]:
        job["on_request"] = True
    job_file = options["job_file"] or overrides["NONAI_JOB_STATE_FILE"]
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps(job), encoding="utf-8")
    return source, tmp, out


def nonai_library_overrides(root: Path, **extra):
    video_lib = root / "videos"
    overrides = {
        "VIDEO_LIBRARY_DIR": video_lib,
        "VIDEO_SEARCH_ROOT": video_lib,
        "NON_AI_DIR": video_lib / "2D" / "non_AI",
        "METADATA_DIR": root / "metadata",
        "SCRIPT_LIBRARY_DIR": root / "scripts",
        "GENERATED_SCRIPTS_DIR": root / "generated",
        "NONAI_RETIRED_ROOT": None,
        "NONAI_PIN_LIST": root / "next.txt",
        "NONAI_SKIP_LIST": root / "skip.txt",
        "NONAI_JOB_STATE_FILE": root / "job.json",
        "NONAI_ATTEMPTS_FILE": root / "attempts.json",
        "NONAI_COOLDOWN_FILE": root / "cooldown.json",
        "NONAI_REQUEST_FILE": root / "request.json",
        "NONAI_FFMPEG_LOG": root / "ffmpeg.log",
        "FUN_TIME_WATCH_STATS_FILE": root / "watch_stats.json",
    }
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
    fields = {
        "id": "2026-07-25T15-20-02",
        "started_at": "2026-07-25T15:20:02",
        "finished_at": "2026-07-25T15:20:14",
        "duration_seconds": 12.0,
        "trigger": "scheduled",
        "status": "success",
        "stages": [],
        "log_start": None,
        "log_end": None,
    }
    fields.update(overrides)
    return RunRecord(**fields)


IDLE_SECONDS_AWAY = 10_000.0

_PROBE_DEFAULTS = {
    "videoai": "", "orientation": "landscape", "duration": 100.0, "free_bytes": 10**15,
    "popen": None, "is_running": True, "image": "ffmpeg.exe", "terminate": True,
    "topaz_pids": (), "arguments": (), "available_ram": 64.0,
    "idle_seconds": IDLE_SECONDS_AWAY,
}


def _topaz_encodes(pids, arguments) -> list[processes.Process]:
    return [processes.Process(pid=pid, ppid=1, started=0.0, name=config.FFMPEG.name,
                              exe=str(config.FFMPEG), cmdline=" ".join(arguments),
                              arguments=tuple(arguments))
            for pid in pids]


def probes(**given):
    options = _given_over(_PROBE_DEFAULTS, given)
    stack = ExitStack()
    # CPython's patch() on a dotted path through a module attribute (tasks.x.processes.suspend)
    # sets the owner's attribute anyway, so those are written on the owner; a name taken in
    # with a from-import is patched where it was imported.
    mocks = {
        "idle_seconds": stack.enter_context(
            patch("tasks.nonai_encode.seconds_since_input",
                  return_value=options["idle_seconds"])),
        "suspend": stack.enter_context(process_suspended(return_value=True)),
        "resume": stack.enter_context(process_resumed(return_value=True)),
        "videoai": stack.enter_context(
            patch("util.ffprobe.videoai_tag", return_value=options["videoai"])),
        "orientation": stack.enter_context(
            patch("util.ffprobe.orientation_of", return_value=options["orientation"])),
        "duration": stack.enter_context(
            patch("util.ffprobe.duration_seconds", return_value=options["duration"])),
        "free_bytes": stack.enter_context(
            patch("util.system_resources.free_bytes", return_value=options["free_bytes"])),
        "available_ram": stack.enter_context(
            patch("util.system_resources.available_ram_gb",
                  return_value=options["available_ram"])),
        "popen": stack.enter_context(
            patch("subprocess.Popen",
                  options["popen"] or Mock(return_value=Mock(pid=4242)))),
        "is_running": stack.enter_context(process_alive(return_value=options["is_running"])),
        "exe": stack.enter_context(process_exe(return_value=options["image"])),
        "terminate": stack.enter_context(process_terminated(return_value=options["terminate"])),
        "running": stack.enter_context(processes_listed(
            side_effect=lambda: _topaz_encodes(options["topaz_pids"], options["arguments"]))),
        "sign_in_expired": stack.enter_context(
            patch("util.topaz.sign_in_expired", return_value=False)),
    }
    return stack, mocks


def ask_for(overrides, video):
    nonai_job.save_request(overrides["NONAI_REQUEST_FILE"], nonai_job.Request(video))


def request_of(overrides):
    return nonai_job.load_request(overrides["NONAI_REQUEST_FILE"])
