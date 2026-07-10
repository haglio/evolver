"""What the backfill tool does once the viewer has named what they are looking at.

Each decision has an inverse, so a mislabelled clip can be taken back: a sidecar is
snapshotted before it is written and restored from that snapshot, and a clip moved to
the weird folder is reclaimed from where it landed.
"""

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


def sidecar_snapshot(video: Path) -> dict | None:
    """*video*'s sidecar payload as it stands, or None when it has no sidecar."""
    path = sidecar_path(video)
    return read(path) if path.is_file() else None


def restore_sidecar(video: Path, snapshot: dict | None) -> None:
    """Put *video*'s sidecar back the way *snapshot* found it.

    A clip that had no sidecar loses the one :func:`record_action` gave it; a clip
    that arrived carrying prompts keeps them and loses only the act.
    """
    path = sidecar_path(video)
    if snapshot is None:
        path.unlink(missing_ok=True)
    else:
        write(path, snapshot)


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


def reclaim_from_weird(destination: Path, video: Path) -> None:
    """Move a discarded clip back from *destination* to where it came from."""
    video.parent.mkdir(parents=True, exist_ok=True)
    _move_once_unlocked(destination, video)


def _move_once_unlocked(source: Path, target: Path) -> None:
    """Rename *source* to *target*, waiting for the player to release it."""
    for attempt in range(_UNLOCK_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == _UNLOCK_ATTEMPTS - 1:
                raise
            time.sleep(_UNLOCK_DELAY_SECONDS)
