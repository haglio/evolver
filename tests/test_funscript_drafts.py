from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from app_support import funscript
from app_support.testing import process_alive, process_exe

from tasks import funscript_drafts
from tasks.script_versions import copy_missing_version_scripts
from tests.temp_helpers import LaneLibrary, touch_video
from util.script_library import is_marked_generated


class FakeGoblin:
    def __init__(self) -> None:
        self.started: list[list[str]] = []
        self.running: set[int] = set()

    def start(self, command: list[str], log: Path) -> int:
        self.started.append(command)
        pid = 1000 + len(self.started)
        self.running.add(pid)
        return pid

    def still_running(self, pid: int) -> bool:
        return pid in self.running


@pytest.fixture
def library(tmp_path):
    lanes = LaneLibrary(tmp_path)
    with lanes.config():
        yield lanes


@pytest.fixture
def goblin_home(tmp_path) -> Path:
    home = tmp_path / "goblin"
    touch_video(home / "venv" / "Scripts" / "python.exe")
    touch_video(home / "GoblinTrainingGrounds" / "goblintrain.py")
    return home


def _drafted(goblin_home: Path, tmp_path: Path, fake: FakeGoblin, **given):
    return funscript_drafts.run(
        goblin=funscript_drafts.Goblin(goblin_home),
        drafting=funscript_drafts.Drafting.kept_in(tmp_path / "state"),
        start=fake.start, still_running=fake.still_running, **given)


def test_a_kino_upscale_with_no_funscript_is_sent_to_goblinscript(library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake)

    assert fake.started == [[
        str(goblin_home / "venv" / "Scripts" / "python.exe"),
        str(goblin_home / "GoblinTrainingGrounds" / "goblintrain.py"),
        "draft", str(upscale),
        "--out", str(tmp_path / "state" / "funscript_drafts"),
        "--force", "--project", "evolver", "--model", "v0.6.0",
    ]]
    assert result.started == 1


def _script_for(library: LaneLibrary, video: Path) -> Path:
    return (library.scripts / video.relative_to(library.library)).with_suffix(".funscript")


def test_an_upscale_that_has_a_funscript_is_left_alone(library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    touch_video(_script_for(library, upscale))
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake)

    assert (fake.started, result.started) == ([], 0)


def test_an_upscale_whose_sorted_source_has_a_funscript_waits_for_the_copy_of_that_one(
        library, goblin_home, tmp_path):
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    source = touch_video(library.sorted_dir / "example-source" / "portrait" / "video one.mp4")
    touch_video(_script_for(library, source))
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake)

    assert (fake.started, result.started) == ([], 0)


def _aged(video: Path, seconds_ago: float) -> Path:
    stamp = time.time() - seconds_ago
    os.utime(video, (stamp, stamp))
    return video


def test_the_newest_upscales_go_first_and_a_run_sends_no_more_than_its_cap(library, goblin_home, tmp_path):
    folder = library.kino_upscales / "landscape" / "example-source"
    _aged(touch_video(folder / "oldest_topaz.mp4"), 300)
    newest = _aged(touch_video(folder / "newest_topaz.mp4"), 100)
    middle = _aged(touch_video(folder / "middle_topaz.mp4"), 200)
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake, max_items=2)

    assert fake.started[0][3:5] == [str(newest), str(middle)]
    assert (result.started, result.waiting) == (2, 1)


def _held_off(goblin_home: Path, tmp_path: Path, fake: FakeGoblin, now: float | None = None) -> str:
    return funscript_drafts.hold_off_reason(
        goblin=funscript_drafts.Goblin(goblin_home),
        drafting=funscript_drafts.Drafting.kept_in(tmp_path / "state"),
        still_running=fake.still_running, now=now)


def test_the_stage_holds_off_while_its_own_batch_is_still_running(library, goblin_home, tmp_path):
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)

    assert _held_off(goblin_home, tmp_path, fake) == funscript_drafts.STILL_DRAFTING


_ACTIONS = [{"at": 0, "pos": 10}, {"at": 400, "pos": 90}, {"at": 800, "pos": 10}]


def _finish(fake: FakeGoblin, tmp_path: Path, goblin_home: Path, drafted: dict[str, list[dict]]) -> None:
    out = tmp_path / "state" / "funscript_drafts"
    out.mkdir(parents=True, exist_ok=True)
    for stem, actions in drafted.items():
        (out / f"{stem}.funscript").write_text(
            json.dumps({"actions": actions, "metadata": {"creator": ""}}), encoding="utf-8")
    touch_video(goblin_home / "GoblinTrainingGrounds" / "projects" / "evolver" / "transcode.mp4")
    fake.running.clear()


def test_a_finished_batch_gives_each_upscale_its_draft_marked_as_made_by_goblinscript(
        library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS})

    result = _drafted(goblin_home, tmp_path, fake)

    script = funscript.read(_script_for(library, upscale))
    assert (script["actions"], script["metadata"]["creator"]) == (_ACTIONS, "GoblinScript v0.6.0")
    assert is_marked_generated(_script_for(library, upscale))
    assert (result.made, result.started) == (1, 0)
    assert not (tmp_path / "state" / "funscript_drafts").exists()
    assert not (goblin_home / "GoblinTrainingGrounds" / "projects" / "evolver").exists()


def test_a_run_while_its_batch_is_still_drafting_leaves_that_batch_alone(library, goblin_home, tmp_path):
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)

    result = _drafted(goblin_home, tmp_path, fake)

    assert (len(fake.started), result.made, result.started) == (1, 0, 0)
    assert _held_off(goblin_home, tmp_path, fake) == funscript_drafts.STILL_DRAFTING


def test_an_upscale_goblinscript_drafts_nothing_usable_for_is_remembered_and_not_sent_again(
        library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video two_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS[:1], "video two_topaz": _ACTIONS})

    taken_in = _drafted(goblin_home, tmp_path, fake)
    _finish(fake, tmp_path, goblin_home, {})
    later = _drafted(goblin_home, tmp_path, fake)

    assert not _script_for(library, upscale).exists()
    assert (taken_in.made, taken_in.nothing_usable, taken_in.started) == (1, 1, 0)
    assert (len(fake.started), later.nothing_usable) == (1, 1)


def test_a_funscript_that_arrived_while_goblinscript_drafted_is_kept(library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    hand_made = touch_video(_script_for(library, upscale))
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS})

    result = _drafted(goblin_home, tmp_path, fake)

    assert (hand_made.read_bytes(), is_marked_generated(hand_made), result.made) == (b"video", False, 0)


def test_a_batch_goblinscript_wrote_nothing_for_fails_and_the_stage_holds_off_for_a_while(
        library, goblin_home, tmp_path):
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake, now=1000.0)
    _finish(fake, tmp_path, goblin_home, {})

    failed = _drafted(goblin_home, tmp_path, fake, now=2000.0)
    held = _held_off(goblin_home, tmp_path, fake, now=2000.0 + funscript_drafts.HOLD_OFF_AFTER_A_FAILURE_SECONDS - 1)
    again = _held_off(goblin_home, tmp_path, fake, now=2000.0 + funscript_drafts.HOLD_OFF_AFTER_A_FAILURE_SECONDS)
    retried = _drafted(goblin_home, tmp_path, fake, now=9e9)

    assert (failed.failed_batches, failed.ok, failed.nothing_usable, failed.started) == (1, False, 0, 0)
    assert (held, again) == (funscript_drafts.GOBLINSCRIPT_FAILED, "")
    assert (retried.started, len(fake.started)) == (1, 2)


@pytest.mark.parametrize("goblin", [None, funscript_drafts.Goblin(Path("Z:/nowhere/goblin"))])
def test_the_stage_holds_off_while_goblinscript_is_not_installed_where_the_settings_say(goblin, tmp_path):
    reason = funscript_drafts.hold_off_reason(
        goblin=goblin, drafting=funscript_drafts.Drafting.kept_in(tmp_path / "state"),
        still_running=FakeGoblin().still_running)

    assert reason == funscript_drafts.GOBLINSCRIPT_MISSING


def test_two_upscales_of_one_name_go_to_goblinscript_in_different_batches(library, goblin_home, tmp_path):
    first = _aged(touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4"), 100)
    _aged(touch_video(library.kino_upscales / "landscape" / "other-source" / "video one_topaz.mp4"), 200)
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake)

    assert fake.started[0][3:-7] == [str(first)]
    assert (result.started, result.waiting) == (1, 1)


def test_an_upscale_in_kinos_trash_gets_no_draft(library, goblin_home, tmp_path):
    touch_video(library.trash / "video one_topaz.mp4")
    fake = FakeGoblin()

    result = _drafted(goblin_home, tmp_path, fake)

    assert (fake.started, result.waiting) == ([], 0)


class FakePopen:
    def __init__(self) -> None:
        self.asked: list[tuple[list[str], dict]] = []

    def __call__(self, command: list[str], **how):
        self.asked.append((command, {**how, "stderr": Path(how["stderr"].name)}))
        return SimpleNamespace(pid=4242)


def test_goblinscript_starts_hidden_and_below_normal_with_its_errors_in_the_stages_log(tmp_path):
    popen = FakePopen()
    log = tmp_path / "state" / "funscript_drafts.log"

    pid = funscript_drafts.launch(["goblin", "draft"], log, popen=popen)

    (command, how), = popen.asked
    assert (pid, command, how["stdout"], how["stderr"]) == (4242, ["goblin", "draft"], subprocess.DEVNULL, log)
    assert how["creationflags"] == subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS


def test_a_batch_is_still_running_only_while_its_pid_is_goblinscripts_python(goblin_home):
    goblin = funscript_drafts.Goblin(goblin_home)
    still_running = funscript_drafts.drafting_by(goblin)

    with process_alive(return_value=True), process_exe(return_value=str(goblin.python).upper()):
        theirs = still_running(4242)
    with process_alive(return_value=True), process_exe(return_value=r"C:\elsewhere\python.exe"):
        reused = still_running(4242)
    with process_alive(return_value=False), process_exe(return_value=str(goblin.python)):
        ended = still_running(4242)

    assert (theirs, reused, ended) == (True, False, False)


def test_an_upscale_deleted_while_goblinscript_drafted_gets_no_funscript(library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    upscale.unlink()
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS})

    result = _drafted(goblin_home, tmp_path, fake)

    assert (_script_for(library, upscale).exists(), result.made) == (False, 0)


def test_the_sorted_video_an_upscale_was_made_from_gets_that_one_draft_from_the_version_copy(
        library, goblin_home, tmp_path):
    upscale = touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    source = touch_video(library.sorted_dir / "example-source" / "portrait" / "video one.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS})
    _drafted(goblin_home, tmp_path, fake)

    copy_missing_version_scripts({"video one_topaz": [upscale], "video one": [source]},
                                 library.library, library.scripts)

    assert _script_for(library, source).read_bytes() == _script_for(library, upscale).read_bytes()
    assert is_marked_generated(_script_for(library, source))
    assert len(fake.started) == 1


def test_the_runs_log_says_what_the_stage_did(library, goblin_home, tmp_path, caplog):
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video one_topaz.mp4")
    touch_video(library.kino_upscales / "portrait" / "example-source" / "video two_topaz.mp4")
    fake = FakeGoblin()
    _drafted(goblin_home, tmp_path, fake)
    _finish(fake, tmp_path, goblin_home, {"video one_topaz": _ACTIONS, "video two_topaz": []})

    with caplog.at_level(logging.INFO, logger=funscript_drafts.__name__):
        _drafted(goblin_home, tmp_path, fake)

    assert caplog.messages[-1] == ("Funscripts made: 1. Videos GoblinScript drafted nothing usable for: 1. "
                                   "Sent to GoblinScript now: 0. Still waiting: 0.")
