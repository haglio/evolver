"""Where a funscript lives, and how to carry one between a clip and its scene —
cut out of the scene's, or placed back into the scene's timeline.

What a funscript *is* belongs to every app in this family that reads or writes
one and lives in :mod:`app_support.funscript`; this module used to say it again.
"""

from __future__ import annotations

from pathlib import Path

from app_support.funscript import actions_of
from app_support.mirrored_tree import mirrored_path

import config


def script_path_for_video(video: Path) -> Path:
    """The funscript mirroring *video*'s path under ``SCRIPT_LIBRARY_DIR``.

    Scripts parallel the video tree the way sidecars do (see
    :func:`util.sidecar.sidecar_path`), so a video's script is found by
    swapping the root and the suffix.

    Raises ``ValueError`` for a video outside the library, which has no script
    here: an archived original keeps its own copy beside it instead.
    """
    script = mirrored_path(
        video,
        roots=(config.VIDEO_LIBRARY_DIR,),
        mirror_root=config.SCRIPT_LIBRARY_DIR,
        suffix=config.FUNSCRIPT_EXTENSION,
    )
    if script is None:
        raise ValueError(f"{video} is not in the video library")
    return script


def trim(script: dict, start_seconds: float, duration_seconds: float) -> dict:
    """The part of *script* covering ``[start, start + duration]``, rebased to zero.

    The action preceding the window is carried forward to ``at == 0`` when the
    window opens between two actions: without it the device holds whatever
    position it was left in and lurches at the clip's first motion, where the
    scene had it already travelling.
    """
    start_ms = round(start_seconds * 1000)
    end_ms = start_ms + round(duration_seconds * 1000)
    source = sorted(actions_of(script), key=lambda action: action["at"])

    inside = [action for action in source if start_ms <= action["at"] <= end_ms]
    before = [action for action in source if action["at"] < start_ms]
    if before and (not inside or inside[0]["at"] != start_ms):
        inside.insert(0, {**before[-1], "at": start_ms})

    actions = [{**action, "at": action["at"] - start_ms} for action in inside]
    trimmed = {**script, "actions": actions}

    metadata = script.get("metadata")
    if isinstance(metadata, dict):
        trimmed["metadata"] = _retime_metadata(metadata, duration_seconds)
    return trimmed


def place(script: dict, start_seconds: float, duration_seconds: float) -> dict:
    """*script* moved to begin *start_seconds* into a *duration_seconds* timeline.

    The reverse of :func:`trim`: where that cuts a clip's script out of its
    scene's, this puts a clip's script back where the clip sits in the scene.
    Nothing is invented for the rest of the scene — a script that says nothing
    over a stretch leaves the device still, which is the truth about a stretch
    nobody has scripted.
    """
    start_ms = round(start_seconds * 1000)
    actions = [
        {**action, "at": action["at"] + start_ms}
        for action in sorted(actions_of(script), key=lambda action: action["at"])
    ]
    placed = {**script, "actions": actions}

    metadata = script.get("metadata")
    if isinstance(metadata, dict):
        placed["metadata"] = _retime_metadata(metadata, duration_seconds)
    return placed


def _retime_metadata(metadata: dict, duration_seconds: float) -> dict:
    """*metadata* re-dated for a timeline of *duration_seconds*.

    Bookmarks and chapters are wall-clock strings into the video they were
    written for, so neither a clip nor a scene inherits the other's: cut loose
    from their timeline they would point at minutes that are not there.
    """
    retimed = dict(metadata)
    if "duration" in retimed:
        retimed["duration"] = int(duration_seconds)
    for absolute in ("bookmarks", "chapters"):
        if absolute in retimed:
            retimed[absolute] = []
    return retimed
