from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from app_support import processes

from tasks import pcloud_stuck

FILE_DELETION, FOLDER_DELETION, UPLOAD, RENAME = 7, 9, 3, 15
STUCK, WAITING = 4, 0
ROOT_FOLDER, SYNCED_FOLDER, FOLDER_ONE = 1, 2, 3


class FakePcloud:
    def __init__(self, tmp: Path):
        self.local = tmp / "local"
        self.drive = tmp / "drive"
        self.db_path = tmp / "data.db"
        (self.local / "videos").mkdir(parents=True)
        (self.drive / "synced" / "videos").mkdir(parents=True)
        self.db = sqlite3.connect(self.db_path)
        self.db.executescript("""
            create table folder (id integer primary key, parentfolderid integer, name text);
            create table file (id integer primary key, parentfolderid integer, name text, size integer);
            create table syncfolder (id integer primary key, folderid integer, localpath text);
            create table localfolder (id integer primary key, localparentfolderid integer, folderid integer, name text);
            create table localfile (id integer primary key, localparentfolderid integer, fileid integer, name text);
            create table task (id integer primary key, type integer, itemid integer, localitemid integer,
                               inprogress integer, attempts integer, err_type integer, err_code integer);
        """)
        self.db.executemany("insert into folder values (?,?,?)", [
            (ROOT_FOLDER, 0, None), (SYNCED_FOLDER, ROOT_FOLDER, "synced"), (FOLDER_ONE, SYNCED_FOLDER, "videos")])
        self.db.execute("insert into syncfolder values (1, ?, ?)", (SYNCED_FOLDER, str(self.local)))
        self.db.execute("insert into localfolder values (10, 0, ?, 'videos')", (FOLDER_ONE,))
        self.db.commit()
        self._next = 100

    def _id(self) -> int:
        self._next += 1
        return self._next

    def cloud_file(self, name: str) -> int:
        file_id = self._id()
        self.db.execute("insert into file values (?,?,?,1)", (file_id, FOLDER_ONE, name))
        self.db.commit()
        (self.drive / "synced" / "videos" / name).write_bytes(b"x")
        return file_id

    def local_file(self, name: str, *, tied_to: int | None = None) -> int:
        local_id = self._id()
        self.db.execute("insert into localfile values (?,10,?,?)", (local_id, tied_to, name))
        self.db.commit()
        (self.local / "videos" / name).write_bytes(b"x")
        return local_id

    def forget_the_local_folder(self) -> None:
        self.db.execute("delete from localfolder")
        self.db.commit()

    def task(self, kind: int, *, item: int = 0, local_item: int = 0, state: int = STUCK) -> int:
        task_id = self._id()
        self.db.execute("insert into task values (?,?,?,?,?,6,3,-2)", (task_id, kind, item, local_item, state))
        self.db.commit()
        return task_id

    def tasks(self) -> list[tuple[int, int, int]]:
        return self.db.execute("select id, inprogress, attempts from task order by id").fetchall()

    def plan(self) -> pcloud_stuck.Plan:
        return pcloud_stuck.plan(self.db, drive=self.drive)


class StandInForTheApp:
    def __init__(self):
        self.running = True
        self.stops = 0

    @contextmanager
    def stopped(self):
        self.running = False
        self.stops += 1
        try:
            yield
        finally:
            self.running = True


@pytest.fixture
def pcloud(tmp_path):
    fake = FakePcloud(tmp_path)
    yield fake
    fake.db.close()


@pytest.fixture
def app():
    return StandInForTheApp()


def run_it(pcloud: FakePcloud, app: StandInForTheApp) -> pcloud_stuck.PcloudStuckResult:
    return pcloud_stuck.run(place=pcloud_stuck.Place(pcloud.db_path, pcloud.drive), app=app)


def test_a_stuck_deletion_of_a_file_the_cloud_no_longer_has_is_dropped(pcloud):
    stuck = pcloud.task(FILE_DELETION, item=999)
    assert pcloud.plan() == pcloud_stuck.Plan(drop=(stuck,))


def test_a_stuck_deletion_of_a_cloud_file_a_file_on_this_computer_now_belongs_to_is_dropped(pcloud):
    kept = pcloud.cloud_file("video one.mp4")
    pcloud.local_file("video one.mp4", tied_to=kept)
    stuck = pcloud.task(FILE_DELETION, item=kept)
    assert pcloud.plan() == pcloud_stuck.Plan(drop=(stuck,))


def test_a_stuck_deletion_of_a_file_only_the_cloud_still_has_is_carried_out_through_the_drive(pcloud):
    pcloud.task(FILE_DELETION, item=pcloud.cloud_file("video two.mp4"))
    assert pcloud.plan() == pcloud_stuck.Plan(delete_in_cloud=(pcloud.drive / "synced" / "videos" / "video two.mp4",))


def test_a_stuck_deletion_is_left_alone_while_this_computer_has_a_file_of_that_name(pcloud):
    left_behind = pcloud.cloud_file("video three.mp4")
    pcloud.local_file("video three.mp4")
    stuck = pcloud.task(FILE_DELETION, item=left_behind)
    assert pcloud.plan() == pcloud_stuck.Plan(left=(stuck,))


def test_a_stuck_upload_is_tried_again_while_its_file_is_still_here_and_dropped_once_it_is_gone(pcloud):
    here = pcloud.task(UPLOAD, local_item=pcloud.local_file("video four.mp4"))
    gone = pcloud.task(UPLOAD, local_item=998)
    assert pcloud.plan() == pcloud_stuck.Plan(drop=(gone,), retry=(here,))


def test_a_stuck_rename_of_nothing_or_of_the_top_of_the_drive_is_dropped_and_any_other_is_left(pcloud):
    of_nothing = pcloud.task(RENAME, item=997)
    of_the_top = pcloud.task(pcloud_stuck.FOLDER_RENAME, item=0)
    of_a_file = pcloud.task(RENAME, item=pcloud.cloud_file("video five.mp4"))
    assert pcloud.plan() == pcloud_stuck.Plan(drop=(of_nothing, of_the_top), left=(of_a_file,))


def test_a_stuck_folder_deletion_of_a_folder_gone_or_belonging_to_a_folder_here_is_dropped(pcloud):
    gone = pcloud.task(FOLDER_DELETION, item=996)
    belongs = pcloud.task(FOLDER_DELETION, item=FOLDER_ONE)
    assert pcloud.plan() == pcloud_stuck.Plan(drop=(gone, belongs))


def test_a_stuck_deletion_of_a_folder_only_the_cloud_still_has_is_carried_out_through_the_drive(pcloud):
    pcloud.forget_the_local_folder()
    (pcloud.local / "videos").rmdir()
    pcloud.task(FOLDER_DELETION, item=FOLDER_ONE)
    assert pcloud.plan() == pcloud_stuck.Plan(delete_in_cloud=(pcloud.drive / "synced" / "videos",))


def test_a_stuck_folder_deletion_is_left_alone_while_this_computer_has_a_folder_of_that_name(pcloud):
    pcloud.forget_the_local_folder()
    stuck = pcloud.task(FOLDER_DELETION, item=FOLDER_ONE)
    assert pcloud.plan() == pcloud_stuck.Plan(left=(stuck,))


def test_a_stuck_change_outside_every_synced_folder_or_of_a_kind_it_does_not_know_is_left(pcloud):
    pcloud.db.execute("delete from syncfolder")
    outside = pcloud.task(FILE_DELETION, item=pcloud.cloud_file("video seven.mp4"))
    unknown = pcloud.task(42)
    assert pcloud.plan() == pcloud_stuck.Plan(left=(outside, unknown))


def test_a_change_pcloud_has_not_given_up_on_is_none_of_its_business(pcloud):
    pcloud.task(FILE_DELETION, item=995, state=WAITING)
    assert pcloud.plan() == pcloud_stuck.Plan()


def test_what_only_the_cloud_still_has_is_deleted_through_the_drive_with_pcloud_left_running(pcloud, app):
    pcloud.task(FILE_DELETION, item=pcloud.cloud_file("video two.mp4"))
    pcloud.forget_the_local_folder()
    (pcloud.local / "videos").rmdir()
    pcloud.task(FOLDER_DELETION, item=FOLDER_ONE)
    result = run_it(pcloud, app)
    assert not (pcloud.drive / "synced" / "videos").exists()
    assert (result.deleted_in_cloud, app.stops) == (2, 0)


def test_changes_with_nothing_left_to_do_are_taken_off_pclouds_list_while_it_is_stopped(pcloud, app):
    pcloud.task(FILE_DELETION, item=999)
    retried = pcloud.task(UPLOAD, local_item=pcloud.local_file("video four.mp4"))
    result = run_it(pcloud, app)
    assert pcloud.tasks() == [(retried, WAITING, 0)]
    assert (result.dropped, result.retried, app.stops, app.running) == (1, 1, 1, True)


def test_pcloud_is_never_stopped_while_it_is_working_on_a_change(pcloud, app):
    pcloud.task(FILE_DELETION, item=999)
    pcloud.task(UPLOAD, local_item=pcloud.local_file("video six.mp4"), state=WAITING)
    run_it(pcloud, app)
    assert app.stops == 0
    assert len(pcloud.tasks()) == 2


def test_a_list_with_nothing_stuck_leaves_pcloud_alone(pcloud, app):
    result = run_it(pcloud, app)
    assert (result.deleted_in_cloud, result.dropped, result.retried, result.left, app.stops) == (0, 0, 0, 0, 0)
    assert not result.needs_an_eye


def test_a_change_it_cannot_judge_is_counted_for_a_look(pcloud, app):
    pcloud.task(RENAME, item=pcloud.cloud_file("video five.mp4"))
    result = run_it(pcloud, app)
    assert result.left == 1
    assert result.needs_an_eye


def test_a_computer_without_pcloud_has_nothing_to_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert pcloud_stuck.Place.on_this_computer() is None
    assert pcloud_stuck.run() == pcloud_stuck.PcloudStuckResult()


def test_pclouds_database_and_drive_are_found_where_pcloud_keeps_them(monkeypatch, tmp_path):
    (tmp_path / "pCloud").mkdir()
    (tmp_path / "pCloud" / "data.db").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(pcloud_stuck, "_pclouds_drive", lambda: Path("Q:\\"))
    assert pcloud_stuck.Place.on_this_computer() == pcloud_stuck.Place(tmp_path / "pCloud" / "data.db", Path("Q:\\"))


class StandInForWindows:
    def __init__(self, running: list[processes.Process]):
        self.running = running
        self.ended: list[int] = []
        self.waited_for: list[int] = []
        self.started: list[list[str]] = []

    def list_running(self) -> list[processes.Process]:
        return list(self.running)

    def terminate(self, pid: int) -> bool:
        self.ended.append(pid)
        return True

    def wait_for_end(self, pid: int) -> bool:
        self.waited_for.append(pid)
        self.running = [process for process in self.running if process.pid != pid]
        return True

    def popen(self, command, **_):
        self.started.append(command)


def a_process(pid: int, name: str) -> processes.Process:
    return processes.Process(pid=pid, ppid=1, started=0.0, name=name, exe="", cmdline="")


def windows_with(monkeypatch, running: list[processes.Process]) -> StandInForWindows:
    windows = StandInForWindows(running)
    monkeypatch.setattr(pcloud_stuck, "_pclouds_drive", lambda: Path("P:\\"))
    monkeypatch.setattr(pcloud_stuck.processes, "running", windows.list_running)
    monkeypatch.setattr(pcloud_stuck.processes, "terminate", windows.terminate)
    monkeypatch.setattr(pcloud_stuck.processes, "wait_for_end", windows.wait_for_end)
    monkeypatch.setattr(pcloud_stuck.subprocess, "Popen", windows.popen)
    return windows


def test_pcloud_is_ended_by_its_own_process_number_and_started_again_through_explorer(monkeypatch):
    windows = windows_with(monkeypatch, [a_process(7, "explorer.exe"), a_process(4321, "pCloud.exe")])
    with pcloud_stuck.Pcloud().stopped():
        assert (windows.ended, windows.waited_for) == ([4321], [4321])
        assert windows.started == []
    assert windows.started == [["explorer.exe", r"C:\Program Files\pCloud Drive\pCloud.exe"]]


def test_the_run_goes_on_only_once_pclouds_drive_is_back(monkeypatch):
    windows_with(monkeypatch, [a_process(4321, "pCloud.exe")])
    drive = iter([None, None, Path("P:\\")])
    monkeypatch.setattr(pcloud_stuck, "_pclouds_drive", lambda: next(drive))
    monkeypatch.setattr(pcloud_stuck.time, "sleep", lambda _seconds: None)

    with pcloud_stuck.Pcloud().stopped():
        pass

    assert next(drive, "asked no more") == "asked no more"


def test_a_drive_that_never_comes_back_holds_the_run_up_a_minute_at_most(monkeypatch):
    windows_with(monkeypatch, [a_process(4321, "pCloud.exe")])
    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(pcloud_stuck, "_pclouds_drive", lambda: None)
    monkeypatch.setattr(pcloud_stuck.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(pcloud_stuck.time, "monotonic", lambda: next(clock))

    with pcloud_stuck.Pcloud().stopped():
        pass

    assert next(clock) <= 75


def test_pcloud_that_is_not_running_is_neither_ended_nor_started(monkeypatch):
    windows = windows_with(monkeypatch, [a_process(7, "explorer.exe")])
    with pytest.raises(RuntimeError), pcloud_stuck.Pcloud().stopped():
        pass
    assert (windows.ended, windows.started) == ([], [])


def test_pcloud_that_windows_will_not_end_is_not_waited_for_or_started_again(monkeypatch):
    windows = windows_with(monkeypatch, [a_process(4321, "pCloud.exe")])
    monkeypatch.setattr(pcloud_stuck.processes, "terminate", lambda pid: False)
    with pytest.raises(RuntimeError), pcloud_stuck.Pcloud().stopped():
        pass
    assert (windows.waited_for, windows.started) == ([], [])
