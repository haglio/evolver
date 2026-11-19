from __future__ import annotations

from pathlib import Path

import pytest

from tasks import nonai_group, nonai_titles, provenance_sweep, video_kinds
from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir
from util import media_files, orientation, run_reads, sidecar


@pytest.fixture
def counted(monkeypatch):
    calls = {"read": 0, "locked": 0}
    real_read, real_locked = sidecar.read_json_or_empty, sidecar.locked_update

    def read(path):
        calls["read"] += 1
        return real_read(path)

    def locked(path, change):
        calls["locked"] += 1
        return real_locked(path, change)

    monkeypatch.setattr(sidecar, "read_json_or_empty", read)
    monkeypatch.setattr(sidecar, "locked_update", locked)
    return calls


def _sidecars(root: Path, count: int) -> list[Path]:
    paths = [root / f"video {number}.json" for number in range(count)]
    for path in paths:
        sidecar.update(path, lambda _: {"title": "Example Title"})
    return paths


def test_while_reads_are_kept_each_sidecar_is_read_once_however_many_ask(counted):
    with workspace_temp_dir() as root:
        paths = _sidecars(root, 5)
        counted["read"] = 0
        with run_reads.kept(run_reads.RunReads()):
            for _ in range(3):
                for path in paths:
                    assert sidecar.read(path) == {"title": "Example Title"}

    assert counted["read"] == 5


def test_while_reads_are_kept_a_change_that_changes_nothing_takes_no_lock(counted):
    with workspace_temp_dir() as root:
        paths = _sidecars(root, 5)
        counted["locked"] = 0
        with run_reads.kept(run_reads.RunReads()):
            for path in paths:
                assert sidecar.update(path, lambda payload: None) is None

    assert counted["locked"] == 0


def test_what_a_kept_update_writes_is_what_the_next_read_sees(counted):
    with workspace_temp_dir() as root:
        path = _sidecars(root, 1)[0]
        with run_reads.kept(run_reads.RunReads()):
            sidecar.read(path)
            sidecar.update(path, lambda payload: {**payload, "kind": "clip"})
            counted["read"] = 0

            assert sidecar.read(path) == {"title": "Example Title", "kind": "clip"}
        assert counted["read"] == 0


def test_without_kept_reads_every_read_goes_to_the_disk(counted):
    with workspace_temp_dir() as root:
        path = _sidecars(root, 1)[0]
        counted["read"] = 0
        sidecar.read(path)
        sidecar.read(path)

    assert counted["read"] == 2


def test_a_forgotten_sidecar_is_read_again(counted):
    with workspace_temp_dir() as root:
        path = _sidecars(root, 1)[0]
        reads = run_reads.RunReads()
        with run_reads.kept(reads):
            sidecar.read(path)
            reads.forget_what_moving_files_changes()
            sidecar.read(path)

    assert counted["read"] == 2


def test_a_folder_walked_while_reads_are_kept_is_walked_once():
    walks = []

    def walk(root):
        walks.append(root)
        return iter([root / "b.mp4", root / "a.mp4"])

    with run_reads.kept(run_reads.RunReads()):
        for _ in range(3):
            assert run_reads.videos_in(Path("library"), walk) == [Path("library/a.mp4"), Path("library/b.mp4")]

    assert walks == [Path("library")]


def test_an_answer_for_the_run_is_worked_out_once_and_outlives_moved_files():
    asked = []
    reads = run_reads.RunReads()
    with run_reads.kept(reads):
        for _ in range(3):
            assert run_reads.once_per_run("folder", lambda: asked.append(1) or "answer") == "answer"
        reads.forget_what_moving_files_changes()
        run_reads.once_per_run("folder", lambda: asked.append(1) or "answer")

    assert asked == [1]
    assert run_reads.once_per_run("folder", lambda: "worked out again") == "worked out again"


def test_the_records_of_a_moved_video_are_read_again_where_it_went(counted):
    with workspace_temp_dir() as root, override_config(VIDEO_LIBRARY_DIR=root / "videos",
                                                       METADATA_DIR=root / "metadata"):
        reads = run_reads.RunReads()
        with run_reads.kept(reads):
            record = sidecar.sidecar_path(root / "videos" / "a.mp4")
            assert sidecar.read(record) == {}
            sidecar.forget(record)
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text('{"title": "Example Title"}', encoding="utf-8")

            assert sidecar.read(record) == {"title": "Example Title"}


def test_while_files_may_move_every_read_goes_to_the_disk_but_the_run_s_answers_stay(counted):
    asked = []
    with workspace_temp_dir() as root:
        path = _sidecars(root, 1)[0]
        counted["read"] = 0
        reads = run_reads.RunReads()
        with run_reads.kept(reads):
            run_reads.once_per_run("folder", lambda: asked.append(1))
            reads.files_may_move(True)
            sidecar.read(path)
            sidecar.read(path)
            run_reads.once_per_run("folder", lambda: asked.append(1))

    assert counted["read"] == 2
    assert asked == [1]



def test_the_non_ai_stages_of_one_run_read_each_sidecar_once_and_walk_the_folder_once(counted, monkeypatch):

    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config():
            videos = [touch_video(lib.non_ai / "lagoon" / "3_good_to_go" / f"video {number}.mp4")
                      for number in range(4)]
            walks = []
            real_walked = media_files._walked
            monkeypatch.setattr(media_files, "_walked",
                                lambda folder: walks.append(folder) or real_walked(folder))
            counted["read"] = 0
            with run_reads.kept(run_reads.RunReads()):
                nonai_group.run(fingerprint=lambda video, seconds: None)
                nonai_titles.run()
                video_kinds.run(probe=lambda video: 60.0,
                                orientation_probe=lambda video: orientation.LANDSCAPE)
                provenance_sweep.run(read_note=lambda video: "")

    assert counted["read"] == len(videos)
    assert walks.count(lib.non_ai) == 1


def test_one_look_works_out_a_run_s_answer_once_and_joins_a_look_already_open():
    asked = []

    with run_reads.one_look():
        run_reads.once_per_run("folder", lambda: asked.append(1))
        with run_reads.one_look():
            run_reads.once_per_run("folder", lambda: asked.append(1))
    with run_reads.one_look():
        run_reads.once_per_run("folder", lambda: asked.append(1))

    assert asked == [1, 1]
