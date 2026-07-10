"""What the backfill tool does once the viewer has named what they are looking at."""

from __future__ import annotations

import time
from pathlib import Path

import config
from util.sidecar import read, sidecar_path, write

# The window moves to the next clip the instant a phrase lands, so the media player
# can still be letting go of the old file when the move runs. Windows refuses to
# rename an open file, so wait it out rather than lose the discard.
_UNLOCK_ATTEMPTS = 10
_UNLOCK_DELAY_SECONDS = 0.2


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
    _move_once_unlocked(video, destination)
    return destination


def _move_once_unlocked(video: Path, destination: Path) -> None:
    """Rename *video* to *destination*, waiting for the player to release it."""
    for attempt in range(_UNLOCK_ATTEMPTS):
        try:
            video.replace(destination)
            return
        except PermissionError:
            if attempt == _UNLOCK_ATTEMPTS - 1:
                raise
            time.sleep(_UNLOCK_DELAY_SECONDS)
