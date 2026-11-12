from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app_support import kino_folder
from app_support.flick_folder import flat_flicks_in, flicks_folder_in, trash_folder_beside

import config
from util import orientation
from util.media_files import is_finalized_video_file, library_videos, listed_videos
from util.versions import upscaled_stem

ORIGENERATOR_SOURCE = "origenerator"

VR_FOLDER = "VR"


@dataclass(frozen=True)
class SentLane:
    key: str
    source: str
    sent_column: str
    unsent_column: str
    upscales: tuple[Path, ...]
    trash: Path

    @property
    def stamps(self) -> tuple[str, str]:
        return self.sent_column, self.unsent_column

    def still_sent(self, row: dict) -> bool:
        return bool(row.get(self.sent_column)) and not row.get(self.unsent_column)


def sent_lanes() -> tuple[SentLane, ...]:
    kino, genau = upscale_lanes()
    return (
        SentLane("evolver", ORIGENERATOR_SOURCE, "evolver_exported_at", "evolver_unsent_at",
                 upscales=tuple(kino.upscales / orient / ORIGENERATOR_SOURCE
                                for orient in orientation.SORTED),
                 trash=kino.trash),
        SentLane("genau", genau_source(), "genau_exported_at", "genau_unsent_at",
                 upscales=() if genau.upscales is None else (genau.upscales,),
                 trash=genau.trash),
    )


@dataclass(frozen=True)
class UpscaleLane:
    genau: bool
    upscales: Path | None
    trash: Path

    def is_for(self, source: str) -> bool:
        return is_genau_lane(source) == self.genau


def _kino() -> Path:
    return config.KINO_DIR


def kino_lane() -> UpscaleLane:
    return UpscaleLane(False, kino_folder.upscales_in(_kino()), kino_folder.trash_folder_in(_kino()))


def genau_lane() -> UpscaleLane:
    return UpscaleLane(True, genau_delivery_dir(), config.GENAU_TRASH_DIR)


def upscale_lanes() -> tuple[UpscaleLane, UpscaleLane]:
    return kino_lane(), genau_lane()


def kino_upscales_dir() -> Path:
    return kino_lane().upscales


def genau_source() -> str:
    return config.GENAU_SOURCE


def is_genau_lane(source: str) -> bool:
    return source == genau_source()


def upscale_of(source: str, orient: str, sorted_stem: str) -> Path | None:
    if not is_genau_lane(source):
        return kino_folder.upscale_in(_kino(), orient, source, sorted_stem)
    genau = genau_delivery_dir()
    return None if genau is None else genau / f"{upscaled_stem(sorted_stem)}.mp4"


def in_trash(upscale: Path) -> Path:
    flicks = genau_flicks_dir()
    if flicks is not None and upscale.is_relative_to(flicks):
        return trash_folder_beside(flicks) / upscale.relative_to(flicks)
    return kino_lane().trash / upscale.name


def upscale_folders() -> tuple[Path, ...]:
    return tuple(lane.upscales for lane in upscale_lanes() if lane.upscales is not None)


def filed_in_kino(library_relative: Path) -> tuple[str, str] | None:
    try:
        kino = kino_upscales_dir().relative_to(config.VIDEO_LIBRARY_DIR).parts
    except ValueError:
        return None
    match library_relative.parts[:len(kino)] == kino and library_relative.parts[len(kino):]:
        case (orient, source, _, *_):
            return orient, source
    return None


def genau_sound_of(flick: Path) -> Path:
    return config.GENAU_AUDIO_DIR / f"{flick.stem}.mp3"


def genau_sent_lane() -> SentLane:
    return next(lane for lane in sent_lanes() if lane.source == genau_source())


def sent_by_origenerator(source: str) -> bool:
    return source in {lane.source for lane in sent_lanes()}


@dataclass(frozen=True)
class AiVideo:
    video: Path
    source: str
    orientation: str
    upscale: Path


def ai_videos() -> Iterator[AiVideo]:
    if not config.SORTED_DIR.is_dir():
        return
    for source_dir in sorted(p for p in config.SORTED_DIR.iterdir() if p.is_dir()):
        for orient_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            for video in sorted(library_videos(orient_dir)):
                upscale = upscale_of(source_dir.name, orient_dir.name, video.stem)
                if upscale is not None:
                    yield AiVideo(video, source_dir.name, orient_dir.name, upscale)


def upscale_filed_for(video: Path) -> Path | None:
    try:
        source, orient, *inside = video.relative_to(config.SORTED_DIR).parts
    except ValueError:
        return None
    return upscale_of(source, orient, video.stem) if inside else None


def genau_flicks_dir() -> Path | None:
    return flicks_folder_in(config.GENAU_DIR)


def genau_delivery_dir() -> Path | None:
    flicks = genau_flicks_dir()
    return None if flicks is None else flat_flicks_in(flicks) / "AI"


def genau_flicks() -> Iterator[Path]:
    flicks = genau_flicks_dir()
    if flicks is None:
        return
    for video in sorted(flicks.rglob("*")):
        if is_finalized_video_file(video):
            yield video


def non_ai_videos() -> list[Path]:
    if not config.NON_AI_DIR.is_dir():
        return []
    return sorted(library_videos(config.NON_AI_DIR))


@dataclass(frozen=True)
class VrVideo:
    video: Path
    in_library: Path


def vr_videos() -> Iterator[VrVideo]:
    return vr_videos_kept_in(config.VR_VIDEO_DIR, config.VIDEO_LIBRARY_DIR)


def vr_videos_kept_in(kept_in: Path | None, library: Path) -> Iterator[VrVideo]:
    if kept_in is None:
        return
    for video in listed_videos(kept_in):
        yield VrVideo(video, library / VR_FOLDER / video.relative_to(kept_in))
