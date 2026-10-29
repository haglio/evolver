"""Stage: record what kind every library video is, how long it runs, and whether
it is portrait or landscape.

Three fields, ``video.type``, ``video.duration_seconds`` and
``video.orientation`` (:mod:`util.video_type`), written once per video and read
by every app in the family in place of the tests they each used to run.  This
stage is the only thing that writes them, so the vocabulary has one author.

It is a *backfill that never ends*: it walks the whole library every run, so
the videos already in the library and the ones that arrive tomorrow are
answered by the same code and there is no one-off script to remember to run.

What it asks each time depends on what the answer costs.  Where a video sits,
and whether its sidecar (or the company it keeps) says something carved it out
of a longer one, are free to read, so those two kinds are re-derived every run — which is what makes the
record self-correcting: declare a folder of excerpts in the overlay, or split a
video and write it a ``clip`` record, and the next run fixes what it wrote
before it knew.  A running time costs an ffprobe, so that answer is remembered
once and never asked again; a video does not change length.

Every video is measured, not only the ones a running time has to settle.  A
free kind — an excerpt, a Genau flick — is named without asking how long the
video is, but the answer is worth having for its own sake: it is what
:mod:`tasks.nonai_progress` weighs the non-AI upscale queue by, and two thirds
of the videos that stage accounts for are excerpts.  Measuring them here costs
one ffprobe apiece, once, against the same batch limit; leaving them to be
measured wherever they are needed costs one per reader forever.

Which means the first run over a library that has never been asked is the
expensive one, and it runs inside a pipeline with a wall clock.  So a run
measures at most ``config.VIDEO_TYPE_BATCH_LIMIT`` videos and leaves the rest
to the next one: a library arrives at a complete answer over a few runs rather
than holding one run up until it has the whole thing.

What it will not do is guess.  A video whose running time is what decides its
kind, and which nothing could measure — a file Topaz still has open, most
often — is skipped rather than written down as full-length because nothing
measured it: the sidecar's silence is recoverable on a later run, a wrong answer
written into it is not.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes, orientation, sidecar, video_type
from util.ffprobe import duration_seconds, orientation_of

log = logging.getLogger(__name__)

_NEITHER_PORTRAIT_NOR_LANDSCAPE = None


@dataclass(frozen=True)
class _Listed:
    """A video whose kind this stage owns, its record as it stands, and what its
    lane settles on its own: the two signals a kind is read off, and the
    orientation of a video the lane files by it (empty where it has to be
    measured)."""

    video: Path
    sidecar: Path
    payload: dict
    genau: bool = False
    excerpt: bool = False
    orientation: str | None = ""
    on_the_cloud_drive: bool = False


@dataclass
class _Measurements:
    left: int
    left_on_the_cloud_drive: int

    def spent_on(self, listed: _Listed) -> bool:
        if self.left <= 0 or (listed.on_the_cloud_drive and self.left_on_the_cloud_drive <= 0):
            return False
        self.left -= 1
        if listed.on_the_cloud_drive:
            self.left_on_the_cloud_drive -= 1
        return True

    def none_more_from_the_cloud_drive(self) -> None:
        self.left_on_the_cloud_drive = 0


@dataclass
class VideoTypesResult:
    """What one run reached, counting each video once.

    ``recorded`` wrote a sidecar, ``already`` found nothing left to ask,
    ``skipped`` could not be measured and so has no kind to write down, and
    ``deferred`` still owes a later run something — a measurement this run had
    none left to spend, or one that failed on a video whose kind it could name
    anyway.
    """

    recorded: int = 0
    already: int = 0
    skipped: int = 0
    deferred: int = 0


def run(probe=duration_seconds, orientation_probe=orientation_of) -> VideoTypesResult:
    """Record what kind every library video is, how long it runs, and whether it
    is portrait or landscape.

    *probe* reads a video's running time and *orientation_probe* its
    orientation; they are the only things here that cost anything, so they are
    what the batch limit counts, and both are test seams.

    A video is measured once — the first run that reaches it and has a
    measurement left to spend — and thereafter its sidecar answers.  The kind
    is then re-derived every run from that recorded time and from the two free
    signals, so a folder declared an excerpt after the fact corrects itself.
    """
    log.info("=== Stage: record video kinds ===")
    result = VideoTypesResult()
    measurements = _Measurements(config.VIDEO_TYPE_BATCH_LIMIT,
                                 config.CLOUD_VIDEO_TYPE_BATCH_LIMIT)
    for listed in _library_videos():
        free = video_type.free_kind(genau=listed.genau, excerpt=listed.excerpt)
        seconds = video_type.duration_of(listed.payload)
        unmeasurable = False
        if seconds is None and measurements.spent_on(listed):
            seconds = probe(listed.video)
            unmeasurable = seconds is None
            if unmeasurable:
                log.info("Could not measure %s; leaving it for the next run", listed.video)
                if listed.on_the_cloud_drive:
                    measurements.none_more_from_the_cloud_drive()
        if seconds is None and not free:
            # Nothing free says what this is and no running time did either, so
            # it is left alone: the sidecar's silence is recoverable on a later
            # run, and a wrong answer written into it is not.
            if unmeasurable:
                result.skipped += 1
            else:
                result.deferred += 1
            continue

        oriented = listed.orientation is not _NEITHER_PORTRAIT_NOR_LANDSCAPE
        orient = (listed.orientation or video_type.orientation_of(listed.payload)) if oriented else ""
        if oriented and not orient and measurements.spent_on(listed):
            orient = _orientation_measured(listed.video, orientation_probe)

        def record_what_is_known(
            current: dict, genau=listed.genau, excerpt=listed.excerpt, seconds=seconds,
            orient=orient,
        ) -> dict | None:
            written = video_type.stamped(
                current, video_type.classify(genau=genau, excerpt=excerpt,
                                             duration_seconds=seconds))
            if seconds is not None:
                written = video_type.timed(written, seconds)
            if orient:
                written = video_type.oriented(written, orient)
            return written if written != current else None

        if sidecar.update(listed.sidecar, record_what_is_known) is not None:
            result.recorded += 1
        elif seconds is None or (oriented and not orient):
            # What it could say already on file, still owing a measurement that
            # this run had none left for, or could not take.
            result.deferred += 1
        else:
            result.already += 1
    log.info(
        "Video kinds: recorded %d, already known %d, skipped %d, deferred %d.",
        result.recorded, result.already, result.skipped, result.deferred,
    )
    return result


def _orientation_measured(video: Path, orientation_probe) -> str:
    measured = orientation_probe(video)
    if measured == orientation.UNKNOWN:
        log.info("Could not tell whether %s is portrait or landscape; leaving it "
                 "for the next run", video)
        return ""
    return measured


def _library_videos():
    yield from _genau_flicks()
    yield from _ai_clips()
    yield from _non_ai_videos()
    yield from _vr_videos()


def _genau_flicks():
    for video in lanes.genau_flicks():
        path = sidecar.sidecar_path(video)
        yield _Listed(video, path, sidecar.read(path), genau=True)


def _ai_clips():
    """Read off ``1_sorted``, which holds the whole AI library while the outbox
    holds only what has been upscaled so far; the sidecar sits at the upscale's
    mirrored path either way."""
    for clip in lanes.ai_clips():
        path = sidecar.sidecar_path(clip.upscale)
        filed_under = clip.orientation if clip.orientation in orientation.SORTED else ""
        yield _Listed(clip.video, path, sidecar.read(path),
                      genau=clip.source == config.GENAU_SOURCE, orientation=filed_under)


def _non_ai_videos():
    """The real-footage library, where a carved scene is what stands out.

    An excerpt is known by the ``clip`` record something wrote when it carved
    it.  For the batches split before anything wrote one, it is known by the
    company it keeps: a folder its librarian filed the batch's cuts into and
    nothing else (:func:`_cut_folders`), or one the overlay declares outright.

    The whole tree, including a folder that holds no stage folders and so is no
    bucket: the Main Funestra plays every one of these, so every one of them is
    asked what it is.
    """
    videos = lanes.non_ai_videos()
    payloads = {video: sidecar.read(sidecar.sidecar_path(video)) for video in videos}
    carved = {video for video, payload in payloads.items() if _was_carved(video, payload)}
    cuts = _cut_folders(
        [_below_the_library(video) for video in videos if video in carved],
        [_below_the_library(video) for video in videos if video not in carved],
    )
    for video in videos:
        excerpt = video in carved or _in_a_cut_folder(_below_the_library(video), cuts)
        yield _Listed(video, sidecar.sidecar_path(video), payloads[video], excerpt=excerpt)


def _vr_videos():
    for vr in lanes.vr_videos():
        path = sidecar.sidecar_path(vr.in_library)
        yield _Listed(vr.video, path, sidecar.read(path),
                      orientation=_NEITHER_PORTRAIT_NOR_LANDSCAPE, on_the_cloud_drive=True)


def _was_carved(video: Path, payload: dict) -> bool:
    """Whether something says outright that *video* came out of a longer one."""
    return isinstance(payload.get("clip"), dict) or _in_an_excerpt_folder(video)


def _below_the_library(video: Path) -> tuple[str, ...]:
    """*video*'s folders below the non-AI root — its batch, then the rest."""
    return video.relative_to(config.NON_AI_DIR).parts[:-1]


def _in_an_excerpt_folder(video: Path) -> bool:
    relative = video.relative_to(config.VIDEO_LIBRARY_DIR).as_posix()
    return any(relative.startswith(folder) for folder in config.EXCERPT_FOLDERS)


def _in_a_cut_folder(folders: tuple[str, ...], cuts: dict[str, str]) -> bool:
    return len(folders) > 1 and cuts.get(folders[0]) == folders[1]


def _cut_folders(
    carved: list[tuple[str, ...]], others: list[tuple[str, ...]]
) -> dict[str, str]:
    """Which folder each batch filed its cuts into, where it has one.

    *carved* holds the folders of the videos something says are cuts, *others*
    those of everything else.  A batch earns an entry only when its cuts have a
    *dominant* second folder, the rest of it has one too, the two differ, and
    each of those folders holds more of its own set than of the other: two sets
    under one batch that share their second folders are separated by their
    sidecars alone, and the folders they share are the pipeline's stages —
    which can never stand in for a division of the library.  Dominant rather
    than unanimous, so one straggler stranded by a move cannot undo a batch
    that HAS been separated.

    Fun Time reads a library the same way when it has no kind to go on
    (``library_handles.cut_folders``); the answer belongs here, where it is
    written down once for everything that asks.
    """
    def by_batch(folders: list[tuple[str, ...]]) -> dict[str, list[tuple[str, ...]]]:
        grouped: dict[str, list[tuple[str, ...]]] = {}
        for path in folders:
            if path:
                grouped.setdefault(path[0], []).append(path)
        return grouped

    cuts, rest = by_batch(carved), by_batch(others)
    found = {}
    for batch, folders in cuts.items():
        mine = _own_second(folders, rest.get(batch, []))
        if mine:
            found[batch] = mine
    return found


def _own_second(band: list[tuple[str, ...]], mate: list[tuple[str, ...]]) -> str:
    mine, theirs = _dominant_second(band), _dominant_second(mate)
    if not mine or not theirs or mine == theirs:
        return ""
    return mine if _holds_mostly(mine, band, mate) and _holds_mostly(theirs, mate, band) else ""


def _holds_mostly(second: str, band: list[tuple[str, ...]], mate: list[tuple[str, ...]]) -> bool:
    return _count_under(second, band) > _count_under(second, mate)


def _count_under(second: str, folders: list[tuple[str, ...]]) -> int:
    return sum(1 for path in folders if len(path) > 1 and path[1] == second)


def _dominant_second(folders: list[tuple[str, ...]]) -> str:
    """The second folder most of *folders* sit under, or "" when they are split
    across several — which is what a set of pipeline stages looks like."""
    seconds = Counter(path[1] for path in folders if len(path) > 1)
    if not seconds:
        return ""
    name, count = seconds.most_common(1)[0]
    return name if count * 2 > sum(seconds.values()) else ""
