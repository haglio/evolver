"""What the backfill tool does once the viewer has named what they are looking at."""

from __future__ import annotations

from pathlib import Path

import config
from util.sidecar import read, sidecar_path, write


def record_action(video: Path, action: str) -> None:
    """Record *action* as *video*'s act, leaving any other metadata it has intact."""
    path = sidecar_path(video)
    payload = read(path)
    payload.setdefault("video", {})["action"] = action
    write(path, payload)


def discard_as_weird(video: Path) -> Path:
    """Move *video* to the weird folder, as Fun Time's "mark as weird" does.

    No metadata is written: the purge_weird stage deletes a weird clip along with
    the ``1_sorted`` source it came from and any sidecar either one left behind.
    Returns where the clip landed.
    """
    config.WEIRD_DIR.mkdir(parents=True, exist_ok=True)
    destination = config.WEIRD_DIR / video.name
    duplicate_index = 1
    while destination.exists():
        destination = config.WEIRD_DIR / f"{video.stem}__dup{duplicate_index}{video.suffix}"
        duplicate_index += 1
    video.replace(destination)
    return destination
