"""What the backfill tool does once the viewer has named what they are looking at.

Each decision has an inverse, so a mislabelled video can be taken back: a sidecar is
snapshotted before it is written and restored from that snapshot, and a video moved to
the trash folder is reclaimed from where it landed.
"""

from __future__ import annotations

from pathlib import Path

import config
from util import sidecar, trash_folders
from util.media_files import retry_while_in_use
from util.sidecar import sidecar_path


def sidecar_snapshot(video: Path) -> dict | None:
    """*video*'s sidecar payload as it stands, or None when it has no sidecar."""
    path = sidecar_path(video)
    return sidecar.read(path) if path.is_file() else None


def restore_sidecar(video: Path, snapshot: dict | None) -> None:
    """Put *video*'s sidecar back the way *snapshot* found it.

    A video that had no sidecar loses the one :func:`record_action` gave it; a video
    that arrived carrying prompts keeps them and loses only the act.
    """
    path = sidecar_path(video)
    if snapshot is None:
        path.unlink(missing_ok=True)
    else:
        sidecar.update(path, lambda _: snapshot)


def send_to_trash(video: Path) -> Path:
    """Move *video* to the trash folder, as Fun Time's "send to Trash" does.

    Returns where the video landed.
    """
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    destination = trash_folders.free_spot_in(config.TRASH_DIR, video.name)
    retry_while_in_use(lambda: video.replace(destination))
    return destination


def reclaim_from_trash(destination: Path, video: Path) -> None:
    """Move a discarded video back from *destination* to where it came from."""
    video.parent.mkdir(parents=True, exist_ok=True)
    retry_while_in_use(lambda: destination.replace(video))
