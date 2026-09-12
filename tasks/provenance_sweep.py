"""Stage: give every library video a record of what made it, wherever it has none."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import origenerator_metadata
from util import lanes, provenance, sidecar, topaz
from util.variants import is_upscaled_stem

log = logging.getLogger(__name__)

# The stamp for one act, asked for only when a video's record lacks it -- and
# None when it cannot be had yet.
StampFor = Callable[[], "dict | None"]


@dataclass(frozen=True)
class _Filled:
    """What filling in one video's record came to."""

    written: frozenset[str] = frozenset()
    waiting: bool = False


@dataclass
class ProvenanceResult:
    looked_up: int = 0
    unknown: int = 0
    already: int = 0
    deferred: int = 0

    def add(self, filled: _Filled) -> None:
        if not filled.written and not filled.waiting:
            self.already += 1
        self.deferred += int(filled.waiting)
        self.looked_up += int(provenance.GENERATION in filled.written)
        self.unknown += len(filled.written - {provenance.GENERATION})


class _Gallery:
    """Origenerator's gallery, read the first time a clip needs it and at most once."""

    def __init__(self) -> None:
        self._generation_of: Callable[[Path], dict] | None = None
        self._unreadable = False

    def generation_of(self, video: Path) -> dict | None:
        """What made *video*, or None while the gallery cannot be read."""
        if self._generation_of is None and not self._unreadable:
            try:
                self._generation_of = origenerator_metadata.generation_records()
            except (FileNotFoundError, sqlite3.Error):
                log.warning("Could not read Origenerator's gallery; its clips wait for "
                            "a run that can.", exc_info=True)
                self._unreadable = True
        return None if self._generation_of is None else self._generation_of(video)


def run() -> ProvenanceResult:
    log.info("=== Stage: record what made each video ===")
    result = ProvenanceResult()
    for path, acts in _what_each_video_went_through(_Gallery()):
        result.add(_fill_in(path, acts))
    log.info("Provenance: looked up %d, recorded as unknown %d, already recorded %d, "
             "waiting on the gallery %d.",
             result.looked_up, result.unknown, result.already, result.deferred)
    return result


def _made_by_evolver() -> dict:
    return provenance.reconstructed("evolver")


def _made_by_the_non_ai_recipe() -> dict:
    return provenance.reconstructed(None, recipe=topaz.NON_AI_UPSCALE.name)


def _what_each_video_went_through(gallery: _Gallery) -> Iterator[tuple[Path, dict[str, StampFor]]]:
    """Every library video that shows an act, with where its record is and a
    stamp for each act it shows."""
    for clip in lanes.ai_clips():
        acts: dict[str, StampFor] = {}
        if clip.source == lanes.ORIGENERATOR_SOURCE:
            acts[provenance.GENERATION] = lambda clip=clip: gallery.generation_of(clip.video)
        if clip.upscale.is_file():
            acts[provenance.UPSCALE] = _made_by_evolver
        if acts:
            yield sidecar.sidecar_path(clip.upscale), acts
    for video in lanes.genau_clips():
        if is_upscaled_stem(video.stem):
            yield sidecar.sidecar_path(video), {provenance.UPSCALE: _made_by_evolver}
    for video in lanes.non_ai_videos():
        if video.stem.endswith(config.NONAI_OUTPUT_SUFFIX):
            yield sidecar.sidecar_path(video), {
                provenance.UPSCALE_NON_AI: _made_by_the_non_ai_recipe}


def _fill_in(path: Path, acts: dict[str, StampFor]) -> _Filled:
    """Record at *path* each of *acts* its record lacks, asking for a stamp only then."""
    recorded = provenance.stamps_of(sidecar.read(path))
    stamps: dict[str, dict] = {}
    waiting = False
    for act, stamp_for in acts.items():
        if act in recorded:
            continue
        stamp = stamp_for()
        if stamp is None:
            waiting = True
        else:
            stamps[act] = stamp
    written = _record(path, stamps) if stamps else set()
    return _Filled(written=frozenset(written), waiting=waiting)


def _record(path: Path, stamps: dict[str, dict]) -> set[str]:
    """File each of *stamps* the record at *path* does not have yet; the acts filed.

    Asked again inside the file's lock, so a stamp that landed since the record
    was read -- the upscale stage writing its own -- is never written over.
    """
    written: set[str] = set()

    def record_what_is_missing(current: dict) -> dict | None:
        missing = {act: stamp for act, stamp in stamps.items()
                   if act not in provenance.stamps_of(current)}
        written.update(missing)
        for act, stamp in missing.items():
            current = provenance.recorded(current, act, stamp)
        return current if missing else None

    sidecar.update(path, record_what_is_missing)
    return written
