from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app_support.video_names import clip_title, version_group_of

from util import sidecar
from util.library_records import TITLE_KEY as TITLE_FIELD
from util.media_files import is_finalized_video_file, path_key
from util.nonai_library import buckets
from util.stage_result import StageResult

log = logging.getLogger(__name__)


@dataclass
class NonAiTitleResult(StageResult):
    titled: int = 0
    videos: int = 0
    written: int = 0


def _scene_matched(payload: dict) -> str:
    clip = payload.get("clip")
    if not isinstance(clip, dict):
        return ""
    return str(clip.get("full_video", "") or "")


def titles_by_family(payloads: dict[Path, dict]) -> dict[str, str]:
    family_by_path = {path_key(video): version_group_of(payload)
                      for video, payload in payloads.items()}
    titles: dict[str, str] = {}
    for payload in payloads.values():
        title = clip_title(payload)
        if not title:
            continue
        for family in (version_group_of(payload), family_by_path.get(path_key(_scene_matched(payload)))):
            if family:
                titles[family] = title
    return titles


def run() -> NonAiTitleResult:
    log.info("=== Stage: title non-AI videos ===")
    result = NonAiTitleResult()
    payloads: dict[Path, dict] = {}
    for bucket in buckets():
        for video in sorted(bucket.rglob("*")):
            if is_finalized_video_file(video):
                payloads[video] = sidecar.read(sidecar.sidecar_path(video))
    result.videos = len(payloads)
    titles = titles_by_family(payloads)

    for video, payload in payloads.items():
        title = clip_title(payload) or titles.get(version_group_of(payload), "")
        if title:
            result.titled += 1

        def record_the_title(existing: dict, title=title) -> dict | None:
            named = dict(existing)
            if title:
                named[TITLE_FIELD] = title
            else:
                named.pop(TITLE_FIELD, None)
            return named if named != existing else None

        if sidecar.update(sidecar.sidecar_path(video), record_the_title) is not None:
            result.written += 1

    log.info(
        "Non-AI titles: named %d of %d video(s); wrote %d sidecar(s).",
        result.titled, result.videos, result.written,
    )
    return result
