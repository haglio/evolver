from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from app_support.video_names import stable_title

from util import lanes, sidecar
from util.frame_hashes import SAMPLE_FPS, Match, align, frame_hashes, locate, sample_frames
from util.media_files import file_size

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_REPEATED_CHARACTER = re.compile(r"(.)\1+")


@dataclass
class ClipMatchResult:
    scenes: int = 0
    clips: int = 0
    matched: int = 0


def could_be_cut_from(clip_record: dict, scene: Path) -> bool:
    performer = _undoubled_tokens(str(clip_record.get("performer", "")))
    return bool(performer) and performer <= _undoubled_tokens(scene.stem)


def record(clip: Path, scene: Path, *, offset: float) -> None:
    def record_the_scene(payload: dict) -> dict:
        payload.setdefault("clip", {}).update(full_video=str(scene), scene_offset=offset)
        return payload

    sidecar.update(sidecar.sidecar_path(clip), record_the_scene)


def forget(clip: Path, scene: Path) -> None:
    def drop_the_match(payload: dict) -> dict | None:
        recorded = payload.get("clip")
        if not isinstance(recorded, dict) or recorded.get("full_video") != str(scene):
            return None
        recorded.pop("full_video", None)
        recorded.pop("scene_offset", None)
        return payload

    sidecar.update(sidecar.sidecar_path(clip), drop_the_match)


def run(
    *,
    videos: Iterable[Path] | None = None,
    fps: float = SAMPLE_FPS,
    sampler: Callable[[Path, float], np.ndarray] = sample_frames,
) -> ClipMatchResult:
    log.info("=== Batch: match carved clips to their scenes ===")
    videos = lanes.non_ai_videos() if videos is None else list(videos)
    payloads = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
    clips = [video for video in videos if isinstance(payloads[video].get("clip"), dict)]
    scenes = _scene_cuts([video for video in videos if video not in set(clips)])
    families = _clip_families(clips, payloads)

    result = ClipMatchResult(scenes=len(scenes), clips=len(clips))
    hashed = _hashed_once(sampler, fps)
    matched = _best_scene_per_clip(_match_every_scene(scenes, clips, payloads, hashed, fps))
    for scene, match in matched.items():
        record(match.clip, scene, offset=match.offset)
        _measure_the_winners_family(match.clip, scene, families[match.clip], hashed, fps)
    result.matched = len(matched)

    log.info("Clip match done. Scenes: %d, clips: %d, matched: %d",
             result.scenes, result.clips, result.matched)
    return result


def _hashed_once(
    sampler: Callable[[Path, float], np.ndarray], fps: float,
) -> Callable[[Path], np.ndarray]:
    hashes: dict[Path, np.ndarray] = {}

    def hashed(video: Path) -> np.ndarray:
        if video not in hashes:
            hashes[video] = frame_hashes(sampler(video, fps))
        return hashes[video]

    return hashed


def _match_every_scene(
    scenes: list[_SceneCut], clips: list[Path], payloads: dict[Path, dict],
    hashed: Callable[[Path], np.ndarray], fps: float,
) -> dict[Path, Match]:
    matched: dict[Path, Match] = {}
    for cut in scenes:
        candidates = [
            clip for clip in clips
            if could_be_cut_from(payloads[clip]["clip"], cut.best_named)
        ]
        if not candidates:
            continue
        found = locate(hashed(cut.cheapest), {c: hashed(c) for c in candidates}, fps=fps)
        if found is not None:
            matched[cut.cheapest] = found
            log.info("%4.0f%% %s @%.1fs <- %s",
                     found.score * 100, cut.cheapest.name, found.offset, found.clip.name)
    return matched


def _measure_the_winners_family(
    winner: Path, scene: Path, family: tuple[Path, ...],
    hashed: Callable[[Path], np.ndarray], fps: float,
) -> None:
    for entry in family:
        if entry == winner:
            continue
        own = align(hashed(entry), hashed(scene), fps=fps)
        if own is None:
            forget(entry, scene)
        else:
            record(entry, scene, offset=own.offset)


@dataclass(frozen=True)
class _SceneCut:
    best_named: Path
    cheapest: Path


def _scene_cuts(scenes: list[Path]) -> list[_SceneCut]:
    families: dict[str, list[Path]] = {}
    for scene in scenes:
        title = stable_title(scene.stem)
        families.setdefault(title or f"\0{scene}", []).append(scene)
    return [
        _SceneCut(best_named=ordered[0], cheapest=ordered[-1])
        for ordered in (_largest_first(family) for family in families.values())
    ]


def _clip_families(clips: list[Path], payloads: dict[Path, dict]) -> dict[Path, tuple[Path, ...]]:
    grouped: dict[str, list[Path]] = {}
    for clip in clips:
        version = payloads[clip].get("version")
        group = version.get("group") if isinstance(version, dict) else None
        grouped.setdefault(str(group) if group else f"\0{clip}", []).append(clip)
    return {clip: tuple(family) for family in grouped.values() for clip in family}


def _best_scene_per_clip(matched: dict[Path, Match]) -> dict[Path, Match]:
    winner: dict[Path, Path] = {}
    for scene, match in matched.items():
        held = winner.get(match.clip)
        if held is None or matched[held].score < match.score:
            winner[match.clip] = scene
    winners = set(winner.values())
    return {scene: match for scene, match in matched.items() if scene in winners}


def _largest_first(videos: list[Path]) -> list[Path]:
    return sorted(videos, key=lambda video: (-file_size(video), str(video)))


def _undoubled_tokens(text: str) -> set[str]:
    return {_REPEATED_CHARACTER.sub(r"\1", token) for token in _TOKEN.findall(text.lower())}
