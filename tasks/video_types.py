"""Stage: record what kind every library video is on its metadata sidecar.

One field, ``video.type`` (:mod:`util.video_type`), written once per video and
read by every app in the family in place of the five different tests they each
used to run.  This stage is the only thing that writes it, so the vocabulary
has one author.

It is a *backfill that never ends*: it walks the whole library every run, so
the videos already in the library and the ones that arrive tomorrow are
answered by the same code and there is no one-off script to remember to run.

What it asks each time depends on what the answer costs.  Where a video sits,
and whether its sidecar says something carved it out of a longer one, are free
to read, so those two kinds are re-derived every run — which is what makes the
record self-correcting: declare a folder of excerpts in the overlay, or split a
video and write it a ``clip`` record, and the next run fixes what it wrote
before it knew.  A running time costs an ffprobe, so that answer is remembered
once and never asked again; a video does not change length.

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
from dataclasses import dataclass
from pathlib import Path

import config
from util import sidecar, video_type
from util.ffprobe import duration_seconds
from util.media_files import is_finalized_video_file, iter_finalized_videos
from util.sidecar import upscaled_video_path

log = logging.getLogger(__name__)

# The kinds a running time settles, and so the ones worth remembering: a video
# does not change length, and re-deriving these would be an ffprobe per video
# per run.
_MEASURED_KINDS = (video_type.SHORT, video_type.FULL_LENGTH)


@dataclass
class VideoTypesResult:
    recorded: int = 0
    already: int = 0
    skipped: int = 0
    deferred: int = 0


def run(probe=duration_seconds) -> VideoTypesResult:
    """Record what kind every library video is, measuring only where it must.

    *probe* reads a video's running time; it is the one thing here that costs
    anything, and a test seam.
    """
    log.info("=== Stage: record video kinds ===")
    result = VideoTypesResult()
    measured = 0
    for video, path, genau, excerpt in _library_videos():
        payload = sidecar.read(path)
        recorded = video_type.type_of(payload)
        free = video_type.free_kind(genau=genau, excerpt=excerpt)
        if free:
            # Free to reach, so asked again every run rather than remembered.
            if recorded == free:
                result.already += 1
                continue
            sidecar.write(path, video_type.stamped(payload, free))
            result.recorded += 1
            continue
        if recorded in _MEASURED_KINDS:
            result.already += 1
            continue
        # Nothing free says what this is, so it has to be measured — the only
        # cost here, so the only thing the batch limit counts, and the only
        # answer that can fail to be reached at all.
        if measured >= config.VIDEO_TYPE_BATCH_LIMIT:
            result.deferred += 1
            continue
        measured += 1
        seconds = probe(video)
        if seconds is None:
            log.info("Could not measure %s; leaving it for the next run", video)
            result.skipped += 1
            continue
        kind = video_type.classify(genau=False, excerpt=False, duration_seconds=seconds)
        sidecar.write(path, video_type.stamped(payload, kind))
        result.recorded += 1
    log.info(
        "Video kinds: recorded %d, already known %d, skipped %d, deferred %d.",
        result.recorded, result.already, result.skipped, result.deferred,
    )
    return result


def _library_videos():
    """Every video whose kind this stage owns, with where its record lives.

    Yields ``(video, sidecar path, genau, excerpt)`` — the two signals a lane
    settles on its own, leaving only the running time to be measured.
    """
    yield from _genau_clips()
    yield from _ai_clips()
    yield from _non_ai_videos()


def _genau_clips():
    """Genau's delivered loops, which the folder alone identifies."""
    if not config.GENAU_CLIPS_DIR.is_dir():
        return
    for video in sorted(config.GENAU_CLIPS_DIR.iterdir()):
        if is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
            yield video, sidecar.sidecar_path(video), True, False


def _ai_clips():
    """The generated clips, read off ``1_sorted`` rather than off the outbox.

    ``1_sorted`` holds the whole AI library — the correspondence check exists to
    keep it that way — while the outbox holds only what has been upscaled so
    far.  The sidecar sits at the *upscale's* mirrored path either way, which is
    the pairing :func:`util.sidecar.upscaled_video_path` names.
    """
    if not config.SORTED_DIR.is_dir():
        return
    for source_dir in sorted(p for p in config.SORTED_DIR.iterdir() if p.is_dir()):
        for orient_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            for video in sorted(iter_finalized_videos(orient_dir, config.VIDEO_EXTENSIONS)):
                path = sidecar.sidecar_path(
                    upscaled_video_path(source_dir.name, orient_dir.name, video.stem)
                )
                yield video, path, source_dir.name == config.GENAU_SOURCE, False


def _non_ai_videos():
    """The real-footage library, where a carved scene is what stands out.

    An excerpt is known by the ``clip`` record something wrote when it carved
    it — and, for the batches that arrived with no record at all, by sitting in
    a folder the overlay declares holds nothing else.

    The whole tree, including the buckets the other non-AI stages exclude: those
    exclusions are about what to group and what to re-encode, and Nau plays
    every one of these, so every one of them is asked what it is.
    """
    if not config.NON_AI_DIR.is_dir():
        return
    for video in sorted(iter_finalized_videos(config.NON_AI_DIR, config.VIDEO_EXTENSIONS)):
        path = sidecar.sidecar_path(video)
        yield video, path, False, _is_excerpt(video, sidecar.read(path))


def _is_excerpt(video: Path, payload: dict) -> bool:
    return isinstance(payload.get("clip"), dict) or _in_an_excerpt_folder(video)


def _in_an_excerpt_folder(video: Path) -> bool:
    relative = video.relative_to(config.VIDEO_LIBRARY_DIR).as_posix()
    return any(relative.startswith(folder) for folder in config.EXCERPT_FOLDERS)
