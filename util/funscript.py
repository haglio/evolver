"""What a funscript is, where it lives, and how to cut a clip's out of its scene's."""

from __future__ import annotations

import json
from pathlib import Path

import config


def read(path: Path) -> dict:
    """A funscript's payload — empty when it is absent or unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write(path: Path, script: dict) -> None:
    """Serialize *script* to *path*, creating the mirrored directory if need be."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(script), encoding="utf-8")


def script_path_for_video(video: Path) -> Path:
    """The funscript mirroring *video*'s path under ``SCRIPT_LIBRARY_DIR``.

    Scripts parallel the video tree the way sidecars do (see
    :func:`util.sidecar.sidecar_path`), so a video's script is found by
    swapping the root and the suffix.
    """
    rel = video.relative_to(config.VIDEO_LIBRARY_DIR)
    return (config.SCRIPT_LIBRARY_DIR / rel).with_suffix(config.FUNSCRIPT_EXTENSION)


def trim(script: dict, start_seconds: float, duration_seconds: float) -> dict:
    """The part of *script* covering ``[start, start + duration]``, rebased to zero.

    The action preceding the window is carried forward to ``at == 0`` when the
    window opens between two actions: without it the device holds whatever
    position it was left in and lurches at the clip's first stroke, where the
    scene had it already travelling.
    """
    start_ms = round(start_seconds * 1000)
    end_ms = start_ms + round(duration_seconds * 1000)
    source = sorted(script.get("actions", []), key=lambda action: action["at"])

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


def _retime_metadata(metadata: dict, duration_seconds: float) -> dict:
    """*metadata* with everything the scene's timeline dated made clip-relative.

    Bookmarks and chapters are wall-clock strings into the scene, so a clip
    inherits none of them: cut loose from their timeline they would point at
    minutes the clip does not contain.
    """
    retimed = dict(metadata)
    if "duration" in retimed:
        retimed["duration"] = int(duration_seconds)
    for absolute in ("bookmarks", "chapters"):
        if absolute in retimed:
            retimed[absolute] = []
    return retimed
