"""Batch: record which library scene each carved clip was cut from, and where.

The library names its scenes for the performer and a hash, with no movie title
to match a clip's own name against, so which scene a compilation clip came out
of is answerable only from the pictures -- :mod:`util.frame_hashes` samples both
sides, hashes them and looks for the offset that lines them up. What it finds
goes into the clip's sidecar as ``clip.full_video`` and ``clip.scene_offset``,
where ``tasks.clip_scripts`` and ``tasks.scene_scripts`` read it back to carry a
funscript between the two, and where the main player reads it to step from a clip to the
scene it belongs to.

Not a pipeline stage, and deliberately: it reads every candidate video end to
end, which is minutes over a library of hundreds, where the pipeline holds
itself to eleven and runs every ten. Run it by hand when the library has gained
scenes or clips worth matching::

    python tools/run_stage.py clip_match
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from util import lanes, sidecar
from util.frame_hashes import SAMPLE_FPS, Match, align, frame_hashes, locate, sample_frames
from util.version_groups import stable_title

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class ClipMatchResult:
    scenes: int = 0
    clips: int = 0
    matched: int = 0


def could_be_cut_from(clip_record: dict, scene: Path) -> bool:
    """Whether *clip_record*'s clip might have been cut from *scene*, on the names.

    The performer is the one thing a library filename reliably carries, so this
    is the widest net worth casting -- and the set the frame search then narrows
    by looking at the pictures. A clip recording no performer casts none.
    """
    performer = _tokens(str(clip_record.get("performer", "")))
    return bool(performer) and performer <= _tokens(scene.stem)


def record(clip: Path, scene: Path, *, offset: float) -> None:
    """Write the scene *clip* came from, and where in it, into *clip*'s sidecar.

    ``scene_offset`` is seconds into *scene* -- what a funscript has to be
    shifted by to fit the clip, and only knowable while the alignment that found
    it is still in hand. ``tasks.scene_scripts`` and ``tasks.clip_scripts``
    shift by it.
    """
    def record_the_scene(payload: dict) -> dict:
        payload.setdefault("clip", {}).update(full_video=str(scene), scene_offset=offset)
        return payload

    sidecar.update(sidecar.sidecar_path(clip), record_the_scene)


def forget(clip: Path, scene: Path) -> None:
    """Drop *clip*'s recorded match, if what it records is *scene*.

    For a file this sweep has just proved is not in *scene* -- a match written
    by an earlier run, when the two were taken for one video. Anything else it
    records is left alone: the sweep only ever measured this one scene, and a
    match to another is not its to overrule.
    """
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
    """Find the clip cut from each scene in the non-AI library, recording it.

    Works from the scenes, which are the complete set: every compilation clip
    came from one of them, while most scenes were never in a compilation and
    correctly end up with no match. Recording waits for the whole sweep, since
    two scenes can turn out to hold one clip; the answer then goes to each
    version of the winning clip that is measurably in that scene too, so it
    holds whichever one is played without being taken on trust.
    """
    log.info("=== Batch: match carved clips to their scenes ===")
    videos = lanes.non_ai_videos() if videos is None else list(videos)
    payloads = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
    clips = [video for video in videos if isinstance(payloads[video].get("clip"), dict)]
    scenes = _scene_cuts([video for video in videos if video not in set(clips)])
    families = _clip_families(clips, payloads)

    result = ClipMatchResult(scenes=len(scenes), clips=len(clips))
    hashes: dict[Path, np.ndarray] = {}

    def hashed(video: Path) -> np.ndarray:
        # A clip is a candidate for every scene of its performer, so cache it.
        if video not in hashes:
            hashes[video] = frame_hashes(sampler(video, fps))
        return hashes[video]

    matched: dict[Path, Match] = {}
    for cut in scenes:
        candidates = [
            clip for clip in clips
            if could_be_cut_from(payloads[clip]["clip"], cut.named_by)
        ]
        if not candidates:
            continue
        found = locate(hashed(cut.cheapest), {c: hashed(c) for c in candidates}, fps=fps)
        if found is not None:
            matched[cut.cheapest] = found
            log.info("%4.0f%% %s @%.1fs <- %s",
                     found.score * 100, cut.cheapest.name, found.offset, found.clip.name)

    matched = _best_scene_per_clip(matched)
    for scene, match in matched.items():
        record(match.clip, scene, offset=match.offset)
        _tell_the_family(match.clip, scene, families[match.clip], hashed, fps)
    result.matched = len(matched)

    log.info("Clip match done. Scenes: %d, clips: %d, matched: %d",
             result.scenes, result.clips, result.matched)
    return result


def _tell_the_family(
    winner: Path, scene: Path, family: tuple[Path, ...],
    hashed: Callable[[Path], np.ndarray], fps: float,
) -> None:
    """Give the winner's other versions the same answer -- if they earn it.

    A scene holds one clip, so a genuine re-encode of the winner cannot also win
    it: it has to be handed the answer to have one at all. But it is asked
    rather than told, since a family read off the name puts two different cuts
    in one -- telling them filed a clip under a scene it is not in, and gave that
    scene the wrong clip's funscript. One that really is another encode aligns
    here too, at its own offset; one that does not is told nothing, and loses
    what an earlier run told it.
    """
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
    """One cut of footage, in every version of it the library holds.

    ``named_by`` is the version whose filename gates the candidates -- the
    biggest, whose name is the fullest. ``cheapest`` is the one actually
    decoded: an upscale is many times the size of its original, minutes rather
    than seconds to read, for pictures that are the same either way.
    """

    named_by: Path
    cheapest: Path


def _scene_cuts(scenes: list[Path]) -> list[_SceneCut]:
    """*scenes* folded so that each cut of footage appears once.

    Versions of one cut agree on their whole reduced title
    (:func:`util.version_groups.stable_title`), which is stricter than the
    prefix rule that families a bucket: a performer's second scene begins with
    her name too, and folding it into her first would decode one and leave the
    other unmatchable. A name that reduces to nothing is a version of nothing
    but itself.
    """
    families: dict[str, list[Path]] = {}
    for scene in scenes:
        title = stable_title(scene.stem)
        families.setdefault(title or f"\0{scene}", []).append(scene)
    return [
        _SceneCut(named_by=ordered[0], cheapest=ordered[-1])
        for ordered in (_largest_first(family) for family in families.values())
    ]


def _clip_families(clips: list[Path], payloads: dict[Path, dict]) -> dict[Path, tuple[Path, ...]]:
    """Each clip mapped to every version of it, itself included.

    From the family ``tasks.nonai_group`` recorded, which is this app's own
    answer to "same video, other version" and the one the players read. A clip
    with no record yet stands alone -- it gains its family on the next run of
    that stage, and until then is nobody's re-encode.
    """
    grouped: dict[str, list[Path]] = {}
    for clip in clips:
        version = payloads[clip].get("version")
        group = version.get("group") if isinstance(version, dict) else None
        grouped.setdefault(str(group) if group else f"\0{clip}", []).append(clip)
    return {clip: tuple(family) for family in grouped.values() for clip in family}


def _best_scene_per_clip(matched: dict[Path, Match]) -> dict[Path, Match]:
    """*matched* with each clip left to the one scene that holds it best.

    The library keeps both a 540p release and a 4k re-release of the odd scene,
    trimmed differently, and a clip really does sit inside each -- but only one
    of them can be its ``full_video``, so the closer alignment takes it rather
    than whichever scene the sweep happened to reach last.
    """
    winner: dict[Path, Path] = {}
    for scene, match in matched.items():
        held = winner.get(match.clip)
        if held is None or matched[held].score < match.score:
            winner[match.clip] = scene
    return {scene: matched[scene] for scene in matched if scene in set(winner.values())}


def _largest_first(videos: list[Path]) -> list[Path]:
    return sorted(videos, key=lambda video: (-_size(video), str(video)))


def _size(video: Path) -> int:
    try:
        return video.stat().st_size
    except OSError:
        return 0


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))
