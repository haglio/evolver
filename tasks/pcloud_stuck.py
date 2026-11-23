from __future__ import annotations

import ctypes
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app_support.subprocess_utils import hidden_subprocess_kwargs

from util.stage_result import StageResult

log = logging.getLogger(__name__)

UPLOAD = 3
FILE_DELETION = 7
FOLDER_DELETION = 9
FOLDER_RENAME = 13
FILE_RENAME = 15
GAVE_UP = 4
THE_TOP_OF_THE_DRIVE = 0


@dataclass(frozen=True)
class Plan:
    delete_in_cloud: tuple[Path, ...] = ()
    drop: tuple[int, ...] = ()
    retry: tuple[int, ...] = ()
    left: tuple[int, ...] = ()


class _Cloud:
    def __init__(self, db: sqlite3.Connection, drive: Path):
        self.drive = drive
        self._folders = {i: (parent, name) for i, parent, name in db.execute(
            "select id, parentfolderid, name from folder")}
        self._files = {i: (parent, name) for i, parent, name in db.execute(
            "select id, parentfolderid, name from file")}
        self._tied_files = {i for (i,) in db.execute("select fileid from localfile where fileid is not null")}
        self._tied_folders = {i for (i,) in db.execute("select folderid from localfolder where folderid is not null")}
        self._local_files = {i for (i,) in db.execute("select id from localfile")}
        self._synced = [(self._names_of(folder), Path(local)) for folder, local in db.execute(
            "select folderid, localpath from syncfolder")]

    def _names_of(self, folder: int) -> tuple[str, ...]:
        names: list[str] = []
        while folder in self._folders:
            parent, name = self._folders[folder]
            if name:
                names.append(name)
            folder = parent
        return tuple(reversed(names))

    def file_names(self, file: int) -> tuple[str, ...] | None:
        if file not in self._files:
            return None
        parent, name = self._files[file]
        return (*self._names_of(parent), name)

    def folder_names(self, folder: int) -> tuple[str, ...] | None:
        return self._names_of(folder) if self.has_folder(folder) else None

    def has_file(self, file: int) -> bool:
        return file in self._files

    def has_folder(self, folder: int) -> bool:
        return folder != THE_TOP_OF_THE_DRIVE and folder in self._folders

    def file_belongs_here(self, file: int) -> bool:
        return file in self._tied_files

    def folder_belongs_here(self, folder: int) -> bool:
        return folder in self._tied_folders

    def still_here(self, local_file: int) -> bool:
        return local_file in self._local_files

    def on_this_computer(self, names: tuple[str, ...]) -> Path | None:
        for synced, local in self._synced:
            if names[:len(synced)] == synced:
                return local.joinpath(*names[len(synced):])
        return None

    def on_the_drive(self, names: tuple[str, ...]) -> Path:
        return self.drive.joinpath(*names)


def plan(db: sqlite3.Connection, *, drive: Path) -> Plan:
    cloud = _Cloud(db, drive)
    delete_in_cloud: list[Path] = []
    drop: list[int] = []
    retry: list[int] = []
    left: list[int] = []
    for task, kind, item, local_item in db.execute(
            "select id, type, itemid, localitemid from task where inprogress = ? order by id", (GAVE_UP,)):
        if kind == UPLOAD:
            (retry if cloud.still_here(local_item) else drop).append(task)
        elif kind in (FILE_RENAME, FOLDER_RENAME):
            exists = cloud.has_file(item) if kind == FILE_RENAME else cloud.has_folder(item)
            (left if exists else drop).append(task)
        elif kind in (FILE_DELETION, FOLDER_DELETION):
            if kind == FILE_DELETION:
                names, belongs = cloud.file_names(item), cloud.file_belongs_here(item)
            else:
                names, belongs = cloud.folder_names(item), cloud.folder_belongs_here(item)
            if names is None or belongs:
                drop.append(task)
                continue
            here = cloud.on_this_computer(names)
            if here is None or here.exists():
                left.append(task)
            else:
                delete_in_cloud.append(cloud.on_the_drive(names))
        else:
            left.append(task)
    return Plan(tuple(delete_in_cloud), tuple(drop), tuple(retry), tuple(left))


@dataclass
class PcloudStuckResult(StageResult):
    deleted_in_cloud: int = 0
    dropped: int = 0
    retried: int = 0
    left: int = 0

    @property
    def needs_an_eye(self) -> bool:
        return self.left > 0


@dataclass(frozen=True)
class Place:
    database: Path
    drive: Path

    @classmethod
    def on_this_computer(cls) -> Place | None:
        database = Path(os.environ.get("LOCALAPPDATA", "")) / "pCloud" / "data.db"
        drive = _pclouds_drive()
        return cls(database, drive) if database.is_file() and drive is not None else None


_PCLOUDS_DRIVE_LABEL = "pCloud Drive"


def _pclouds_drive() -> Path | None:
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        label = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(f"{letter}:\\", label, 261, None, None, None, None, 0) \
                and label.value == _PCLOUDS_DRIVE_LABEL:
            return Path(f"{letter}:\\")
    return None


class TheApp(Protocol):
    def stopped(self) -> AbstractContextManager[None]: ...


class Pcloud:
    _EXE = Path(r"C:\Program Files\pCloud Drive\pCloud.exe")
    _IMAGE = "pCloud.exe"
    _EXIT_WAIT_S = 30.0

    @contextmanager
    def stopped(self) -> Iterator[None]:
        pid = self._pid()
        if pid is None:
            raise RuntimeError("pCloud is not running")
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True,
                       **hidden_subprocess_kwargs())
        deadline = time.monotonic() + self._EXIT_WAIT_S
        while self._pid() == pid:
            if time.monotonic() > deadline:
                raise RuntimeError("pCloud did not stop")
            time.sleep(0.5)
        try:
            yield
        finally:
            subprocess.Popen(["explorer.exe", str(self._EXE)], **hidden_subprocess_kwargs())

    def _pid(self) -> int | None:
        listed = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {self._IMAGE}", "/FO", "CSV", "/NH"],
                                check=False, capture_output=True, text=True, **hidden_subprocess_kwargs()).stdout
        for line in listed.splitlines():
            fields = line.strip().strip('"').split('","')
            if len(fields) > 1 and fields[0].lower() == self._IMAGE.lower():
                return int(fields[1])
        return None


def _read_only(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database.as_uri()}?mode=ro&immutable=1", uri=True)


def _working_on_something(db: sqlite3.Connection) -> bool:
    return db.execute("select 1 from task where inprogress != ? limit 1", (GAVE_UP,)).fetchone() is not None


def _delete_through_the_drive(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()
    else:
        return False
    return True


def _take_off_the_list(db: sqlite3.Connection, found: Plan) -> None:
    db.executemany("delete from task where id = ? and inprogress = ?", [(task, GAVE_UP) for task in found.drop])
    db.executemany("update task set attempts = 0, inprogress = 0, err_type = 0, err_code = 0 "
                   "where id = ? and inprogress = ?", [(task, GAVE_UP) for task in found.retry])
    db.commit()


def run(*, place: Place | None = None, app: TheApp | None = None) -> PcloudStuckResult:
    place = place or Place.on_this_computer()
    result = PcloudStuckResult()
    if place is None:
        return result
    with closing(_read_only(place.database)) as db:
        found = plan(db, drive=place.drive)
        busy = _working_on_something(db)
    result.left = len(found.left)
    result.deleted_in_cloud = sum(_delete_through_the_drive(path) for path in found.delete_in_cloud)
    if not found.delete_in_cloud and not busy and (found.drop or found.retry):
        with (app or Pcloud()).stopped(), closing(sqlite3.connect(place.database)) as db:
            again = plan(db, drive=place.drive)
            _take_off_the_list(db, again)
            result.dropped, result.retried = len(again.drop), len(again.retry)
    log.info("pCloud's stuck changes: %d deleted in the cloud, %d taken off its list, %d tried again, %d left",
             result.deleted_in_cloud, result.dropped, result.retried, result.left)
    return result
