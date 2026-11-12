from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app_support.kino_folder import is_ai_video

import config
from util import ffprobe, lanes, provenance, sidecar, topaz
from util.stage_result import StageResult
from util.versions import is_upscaled_stem

log = logging.getLogger(__name__)

FFPROBE_READS_OF_TOPAZ_NOTES_PER_RUN = 400

StampFor = Callable[[], "dict | None"]


@dataclass(frozen=True)
class _Filled:
    written: dict[str, dict] = field(default_factory=dict)
    waiting: bool = False


@dataclass
class ProvenanceResult(StageResult):
    from_notes: int = 0
    unknown: int = 0
    already: int = 0
    deferred: int = 0

    def add(self, filled: _Filled) -> None:
        if not filled.written and not filled.waiting:
            self.already += 1
        self.deferred += int(filled.waiting)
        for stamp in filled.written.values():
            if stamp.get(provenance.METHOD) is not None:
                self.from_notes += 1
            else:
                self.unknown += 1


class _Notes:
    def __init__(self, read_note: Callable[[Path], str], limit: int) -> None:
        self._read_note = read_note
        self._left = limit

    def made(self, video: Path) -> dict | None:
        if self._left <= 0:
            return None
        self._left -= 1
        settings = topaz.settings_noted(self._read_note(video))
        if settings is None:
            return provenance.reconstructed(None)
        return provenance.reconstructed("evolver", method=settings.name)


def run(read_note: Callable[[Path], str] = ffprobe.videoai_tag,
        notes_per_run: int = FFPROBE_READS_OF_TOPAZ_NOTES_PER_RUN) -> ProvenanceResult:
    log.info("=== Stage: record what made each video ===")
    result = ProvenanceResult()
    notes = _Notes(read_note, notes_per_run)
    for path, acts in _what_each_video_went_through(notes):
        result.add(_fill_in(path, acts))
    log.info("Provenance: named by their note %d, unknown %d, "
             "already recorded %d, left for a later run %d.",
             result.from_notes, result.unknown, result.already, result.deferred)
    return result


def _what_each_video_went_through(notes: _Notes) -> Iterator[tuple[Path, dict[str, StampFor]]]:
    for video in lanes.genau_flicks():
        if is_upscaled_stem(video.stem) and not is_ai_video(video):
            yield sidecar.sidecar_path(video), {
                provenance.UPSCALE: lambda video=video: notes.made(video)}
    for video in lanes.non_ai_videos():
        if video.stem.endswith(config.NONAI_OUTPUT_SUFFIX):
            yield sidecar.sidecar_path(video), {
                provenance.UPSCALE_NON_AI: lambda video=video: notes.made(video)}


def _fill_in(path: Path, acts: dict[str, StampFor]) -> _Filled:
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
    return _Filled(written=_record(path, stamps) if stamps else {}, waiting=waiting)


def _record(path: Path, stamps: dict[str, dict]) -> dict[str, dict]:
    written: dict[str, dict] = {}

    def record_what_is_missing(current: dict) -> dict | None:
        missing = {act: stamp for act, stamp in stamps.items()
                   if act not in provenance.stamps_of(current)}
        written.update(missing)
        for act, stamp in missing.items():
            current = provenance.recorded(current, act, stamp)
        return current if missing else None

    sidecar.update(path, record_what_is_missing)
    return written
