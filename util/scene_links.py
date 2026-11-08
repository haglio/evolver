from __future__ import annotations

from pathlib import Path

from app_support import video_ids

from util import sidecar

SCENE_ID = "full_video_id"
_SCENE_PATH = "full_video"


def link_to(scene: Path) -> dict[str, str]:
    return {SCENE_ID: video_ids.id_of(sidecar.sidecar_path(scene))}


def scene_id(clip: dict) -> str | None:
    given = clip.get(SCENE_ID)
    return given if isinstance(given, str) and given else None


def names(clip: dict, scene: Path) -> bool:
    given = scene_id(clip)
    return given is not None and given == video_ids.recorded_id(
        sidecar.read(sidecar.sidecar_path(scene)))


def without_a_scene(clip: dict) -> dict:
    return {key: value for key, value in clip.items() if key not in (SCENE_ID, _SCENE_PATH)}


def scene_of(clip: dict, videos_by_id: dict[str, Path]) -> Path | None:
    given = scene_id(clip)
    return videos_by_id.get(given) if given is not None else None


def videos_by_id() -> dict[str, Path]:
    return sidecar.videos_by_id()


def moved_to_ids(video: Path) -> dict:
    record = sidecar.sidecar_path(video)
    payload = sidecar.read(record)
    if _named_by_id(payload) is None:
        return payload
    return sidecar.update(record, _named_by_id) or sidecar.read(record)


def _named_by_id(payload: dict) -> dict | None:
    clip = payload.get("clip")
    named = clip.get(_SCENE_PATH) if isinstance(clip, dict) else None
    if not isinstance(named, str) or not Path(named).is_file():
        return None
    try:
        link = link_to(Path(named))
    except ValueError:
        return None
    return {**payload, "clip": {**without_a_scene(clip), **link}}
