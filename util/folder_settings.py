"""The sibling apps' settings that name a library folder, and what each one held.

A video is followed by its name; a folder is followed by the videos it held, so
every run remembers them while the folder is there, and the run that finds it
gone asks where they went (:func:`util.video_locator.relocate_folder`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath

from app_support.file_channel import write_whole

import config
from util.json_reads import read_dict, read_dict_strict
from util.media_files import library_videos

_SOUND_FOLDER = "ambient_audio_dir"


@dataclass(frozen=True)
class FolderSetting:
    label: str
    path: Path
    _read: Callable[[Path], Path | None]
    _rewrite: Callable[[Path, Path], None]
    _shape: Callable[[Path], str | None]

    def folder(self) -> Path | None:
        return self._read(self.path)

    def repoint(self, folder: Path) -> None:
        self._rewrite(self.path, folder)

    def shape_complaint(self) -> str | None:
        return self._shape(self.path)


def discover() -> Iterator[FolderSetting]:
    overlay = config.ORIGENERATOR_OVERLAY_FILE
    if overlay.is_file():
        yield FolderSetting("origenerator sound folder", overlay,
                            _read_sound_folder, _rewrite_sound_folder, _sound_folder_complaint)


def held(folder: Path) -> list[PurePath]:
    return sorted(video.relative_to(folder) for video in library_videos(folder))


def remember(label: str, folder: Path, videos: list[PurePath]) -> None:
    memory_file = config.FOLLOWED_FOLDERS_FILE
    memory = read_dict(memory_file)
    entry = {"folder": str(folder), "videos": [str(video) for video in videos]}
    if memory.get(label) != entry:
        memory[label] = entry
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        write_whole(memory_file, json.dumps(memory, indent=2) + "\n")


def remembered(label: str, folder: Path) -> list[PurePath]:
    entry = read_dict(config.FOLLOWED_FOLDERS_FILE).get(label)
    if not isinstance(entry, dict) or Path(entry.get("folder") or "") != folder:
        return []
    return [PurePath(video) for video in entry.get("videos") or []]


def _read_sound_folder(path: Path) -> Path | None:
    overlay = read_dict_strict(path)
    named = overlay.get(_SOUND_FOLDER)
    if not named:
        return None
    folder = Path(named)
    return folder if folder.is_absolute() else Path(overlay["library_root"]) / folder


def _rewrite_sound_folder(path: Path, folder: Path) -> None:
    text = path.read_text(encoding="utf-8", newline="")
    overlay = json.loads(text)
    named = overlay[_SOUND_FOLDER]
    renamed = _written_like(named, folder, Path(overlay["library_root"]))
    write_whole(path, text.replace(_literal(named), _literal(renamed)), newline="")


def _written_like(named: str, folder: Path, library_root: Path) -> str:
    form = (folder.relative_to(library_root)
            if not Path(named).is_absolute() and folder.is_relative_to(library_root)
            else folder)
    return str(PureWindowsPath(form)) if "\\" in named else form.as_posix()


def _sound_folder_complaint(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    overlay = json.loads(text)
    named = overlay.get(_SOUND_FOLDER)
    if not named:
        return None
    if not isinstance(named, str) or not isinstance(overlay.get("library_root"), str):
        return f"{_SOUND_FOLDER} or library_root is not a folder"
    if text.count(_literal(named)) != 1:
        return f"{_SOUND_FOLDER}'s value is not written once, as JSON writes it"
    return None


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
