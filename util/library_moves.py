from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from util import script_library, sidecar
from util.media_files import retry_while_in_use

MIRRORS = (sidecar.sidecar_path, script_library.script_path_for_video)


def move_with_its_script(video: Path, dest: Path) -> None:
    retry_while_in_use(lambda: video.replace(dest))
    _move_mirrors(video, dest, (script_library.script_path_for_video,))


def move_its_records(video: Path, dest: Path) -> None:
    _move_mirrors(video, dest, MIRRORS)


def _move_mirrors(video: Path, dest: Path, mirrors: Iterable[Callable[[Path], Path]]) -> None:
    for mirror in mirrors:
        try:
            src, dst = mirror(video), mirror(dest)
        except ValueError:
            continue
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
            if mirror is script_library.script_path_for_video:
                script_library.carry_mark(src, dst)
