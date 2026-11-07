from __future__ import annotations

from pathlib import Path

from util import script_library, sidecar
from util.media_files import retry_while_in_use

MIRRORS = (sidecar.sidecar_path, script_library.script_path_for_video)


def move_with_its_records(video: Path, dest: Path) -> None:
    retry_while_in_use(lambda: video.replace(dest))
    move_its_records(video, dest)


def move_its_records(video: Path, dest: Path) -> None:
    for mirror in MIRRORS:
        src = mirror(video)
        if not src.exists():
            continue
        dst = mirror(dest)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
    script_library.carry_mark(script_library.script_path_for_video(video),
                              script_library.script_path_for_video(dest))
