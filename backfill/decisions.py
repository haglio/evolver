"""What the backfill tool does once the viewer has named what they are looking at.

Each decision has an inverse, so a mislabelled clip can be taken back: a sidecar is
snapshotted before it is written and restored from that snapshot, and a clip moved to
the weird folder is reclaimed from where it landed.
"""

from __future__ import annotations

from pathlib import Path

import config
from util import sidecar, weird_piles
from util.media_files import retry_while_in_use
from util.sidecar import sidecar_path


def sidecar_snapshot(clip: Path) -> dict | None:
    """*clip*'s sidecar payload as it stands, or None when it has no sidecar."""
    path = sidecar_path(clip)
    return sidecar.read(path) if path.is_file() else None


def restore_sidecar(clip: Path, snapshot: dict | None) -> None:
    """Put *clip*'s sidecar back the way *snapshot* found it.

    A clip that had no sidecar loses the one :func:`record_action` gave it; a clip
    that arrived carrying prompts keeps them and loses only the act.
    """
    path = sidecar_path(clip)
    if snapshot is None:
        path.unlink(missing_ok=True)
    else:
        sidecar.update(path, lambda _: snapshot)


def discard_as_weird(clip: Path) -> Path:
    """Move *clip* to the weird folder, as Fun Time's "mark as weird" does.

    Returns where the clip landed.
    """
    config.WEIRD_DIR.mkdir(parents=True, exist_ok=True)
    destination = weird_piles.free_spot_in(config.WEIRD_DIR, clip.name)
    retry_while_in_use(lambda: clip.replace(destination))
    return destination


def reclaim_from_weird(destination: Path, clip: Path) -> None:
    """Move a discarded clip back from *destination* to where it came from."""
    clip.parent.mkdir(parents=True, exist_ok=True)
    retry_while_in_use(lambda: destination.replace(clip))
