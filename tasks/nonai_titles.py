"""Stage: record what to call each 2D/non_AI video, on its mirrored sidecar.

Every app in the family shows a video's name somewhere -- Fun Time's browser
tiles, the name its players print over the picture, the same line in the headset
-- and until this stage the only name any of them had was the filename, which is
whatever the download called it.  A name is worked out once here and read
everywhere, rather than each reader walking the library to work it out again at
launch.

The answer is the ``clip`` record: a clip carved out of a compilation was
recorded with the performer and the movie it came from, which is the name.  A
whole scene has no such record of its own, so it takes the name of the clip
Evolver's clip-match batch found inside it -- the library saved that scene under
whatever the download called it, and the clip is the only thing that knows what
is in it.  A video neither names keeps no ``title`` at all, and its readers fall
back to the filename as they always did.

Like :mod:`tasks.video_types` this is a backfill that never ends: it walks the
whole non-AI library every run and rewrites what it finds, so a clip matched to
its scene tomorrow is titled on the next run with no one-off script to remember.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from util import sidecar
from util.library_records import TITLE_KEY as TITLE_FIELD
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets

log = logging.getLogger(__name__)



@dataclass
class NonAiTitleResult:
    """What one run reached: how many videos it could name, of how many, and how
    many sidecars that came to rewriting."""

    titled: int = 0
    videos: int = 0
    written: int = 0


def clip_title(payload: dict) -> str:
    """What *payload*'s clip record calls the scene -- "performer - movie".

    ``""`` for a video no clip record describes, and for one naming neither half.
    """
    clip = payload.get("clip")
    if not isinstance(clip, dict):
        return ""
    parts = (str(clip.get(field, "") or "").strip() for field in ("performer", "source"))
    return " - ".join(part for part in parts if part)


def family_of(payload: dict) -> str:
    """The version family Evolver grouped *payload*'s video under, or ""."""
    version = payload.get("version")
    if not isinstance(version, dict):
        return ""
    return str(version.get("group") or "")


def _scene_matched(payload: dict) -> str:
    """The scene Evolver's clip-match batch found *payload*'s clip inside."""
    clip = payload.get("clip")
    if not isinstance(clip, dict):
        return ""
    return str(clip.get("full_video", "") or "")


def _path_key(path: str | Path) -> str:
    return str(path).strip().lower()


def titles_by_family(payloads: dict[Path, dict]) -> dict[str, str]:
    """What to call each version family a clip record speaks for.

    Keyed by family rather than by path, since a match is recorded against the
    one rendition that was searched while the apps play whichever they like.
    """
    family_by_path = {_path_key(video): family_of(payload)
                      for video, payload in payloads.items()}
    titles: dict[str, str] = {}
    for payload in payloads.values():
        title = clip_title(payload)
        if not title:
            continue
        for family in (family_of(payload), family_by_path.get(_path_key(_scene_matched(payload)))):
            if family:
                titles[family] = title
    return titles


def run() -> NonAiTitleResult:
    """Title every non-AI video a clip record can name, on its own sidecar."""
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
        title = clip_title(payload) or titles.get(family_of(payload), "")
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
