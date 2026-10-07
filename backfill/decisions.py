"""What the backfill tool does once the viewer has named what they are looking at.

Each decision has an inverse, so a mislabelled clip can be taken back: a sidecar is
snapshotted before it is written and restored from that snapshot, and a clip moved to
the weird folder is reclaimed from where it landed.
"""

from __future__ import annotations

from pathlib import Path

import config
from util import sidecar
from util.media_files import retry_while_in_use
from util.sidecar import WRONG_ACTION_FIELD, sidecar_path


def record_action(clip: Path, action: str) -> None:
    """Record *action* as *clip*'s act, leaving any other metadata it has intact.

    A ``wrong_action`` marker is the exception: it is the standing question this
    answers — a viewer's "that label is wrong, ask me again" — so naming the act
    retires it.  Left in place it would send the clip to the head of this queue
    every time the tool opened.
    """
    def name_the_act(payload: dict) -> dict:
        block = payload.setdefault("video", {})
        block["action"] = action
        block.pop(WRONG_ACTION_FIELD, None)
        return payload

    sidecar.update(sidecar_path(clip), name_the_act)


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
    destination = config.WEIRD_DIR / clip.name
    duplicate_index = 1
    while destination.exists():
        destination = config.WEIRD_DIR / f"{clip.stem}__dup{duplicate_index}{clip.suffix}"
        duplicate_index += 1
    retry_while_in_use(lambda: clip.replace(destination))
    return destination


def reclaim_from_weird(destination: Path, clip: Path) -> None:
    """Move a discarded clip back from *destination* to where it came from."""
    clip.parent.mkdir(parents=True, exist_ok=True)
    retry_while_in_use(lambda: destination.replace(clip))
