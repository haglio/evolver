"""Every video the library holds, lane by lane."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from util.media_files import is_finalized_video_file, library_videos
from util.sidecar import upscaled_video_path

#: The source folder Origenerator's videos arrive under, in 0_inbox and 1_sorted.
ORIGENERATOR_SOURCE = "origenerator"


@dataclass(frozen=True)
class SentLane:
    """One lane Origenerator hands a clip down, seen from the receiving end.

    ``source`` is the ``0_inbox`` folder the clip arrives under -- the whole of
    what a send says, since routing by that name is the only thing passing
    between the two apps -- and ``unsent_column`` is where Origenerator's gallery
    records a send being taken back. Both are names agreed with that repo and
    must stay spelled as it spells them.

    ``delivered_dir`` is where a finished clip of this lane leaves the library
    for, or ``None`` for the lane whose clips stay in the outbox. It is the one
    way the two differ, and it is why a withdrawal has to be answered here: by
    the time one is asked for, the clip has been sorted, upscaled and in that
    lane's case moved somewhere Origenerator has never heard of.
    """

    source: str
    unsent_column: str
    delivered_dir: Path | None


def sent_lanes() -> tuple[SentLane, ...]:
    """Both lanes Origenerator sends down, resolved against config as it is now.

    A function rather than a table, for the reason ``weird_piles`` is one: the
    Genau lane's folder name comes from the overlay, and a tuple built at import
    freezes whatever ``config`` held then.
    """
    return (
        SentLane(ORIGENERATOR_SOURCE, "evolver_unsent_at", delivered_dir=None),
        SentLane(config.GENAU_SOURCE, "genau_unsent_at",
                 delivered_dir=config.GENAU_CLIPS_DIR),
    )


@dataclass(frozen=True)
class AiClip:
    video: Path
    source: str
    orientation: str

    @property
    def upscale(self) -> Path:
        return upscaled_video_path(self.source, self.orientation, self.video.stem)


def ai_clips() -> Iterator[AiClip]:
    if not config.SORTED_DIR.is_dir():
        return
    for source_dir in sorted(p for p in config.SORTED_DIR.iterdir() if p.is_dir()):
        for orient_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            for video in sorted(library_videos(orient_dir)):
                yield AiClip(video, source_dir.name, orient_dir.name)


def genau_clips() -> Iterator[Path]:
    if not config.GENAU_CLIPS_DIR.is_dir():
        return
    for video in sorted(config.GENAU_CLIPS_DIR.iterdir()):
        if is_finalized_video_file(video):
            yield video


def non_ai_videos() -> list[Path]:
    if not config.NON_AI_DIR.is_dir():
        return []
    return sorted(library_videos(config.NON_AI_DIR))
