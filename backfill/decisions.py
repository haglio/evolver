from __future__ import annotations

from pathlib import Path

import config
from util import sidecar, trash_folders
from util.media_files import retry_while_in_use
from util.sidecar import sidecar_path


def sidecar_snapshot(video: Path) -> dict | None:
    path = sidecar_path(video)
    return sidecar.read(path) if path.is_file() else None


def restore_sidecar(video: Path, snapshot: dict | None) -> None:
    path = sidecar_path(video)
    if snapshot is None:
        path.unlink(missing_ok=True)
    else:
        sidecar.update(path, lambda _: snapshot)


def send_to_trash(video: Path) -> Path:
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    destination = trash_folders.free_spot_in(config.TRASH_DIR, video.name)
    retry_while_in_use(lambda: video.replace(destination))
    return destination


def reclaim_from_trash(destination: Path, video: Path) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    retry_while_in_use(lambda: destination.replace(video))
