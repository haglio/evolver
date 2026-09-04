"""How far through the non-AI upscale project the library is, by running time.

The stage could always say how many clips were queued, and a count is the wrong
unit for a queue whose members run from forty seconds to an hour: when this was
written the library was 59% upscaled by clip and 29% by running time, because
what went first was the short stuff.  Hours left is the number a person wants,
and a percentage of hours is the one that moves at a rate they can believe.

The project is what the queue holds plus what the library has already been
given: every bucket video with a processed variant counts as done, whoever made
it — a good part of the library was upscaled by hand in the Topaz GUI before
this stage existed, and those are as finished as anything it promoted.  What is
in neither set is in neither total, because the project cannot reach it: a clip
in a sub-stage that still wants a human with a trimmer, one the skip manifest
retired, one sitting in a bucket's "good to go" that nobody asked to re-encode.

Nothing here measures anything.  A running time comes off the video's sidecar,
where :mod:`tasks.video_types` writes it once (:mod:`util.video_type`), so this
costs a walk and a JSON read per video instead of four hundred ffprobe spawns
every ten minutes.  A video nothing has measured yet is counted apart rather
than guessed at, so over the first runs against a library that has never been
asked, the percentage says how much of itself it can see.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import config
from util import sidecar, video_type
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets
from util.variants import is_processed_stem, strip_processing_suffixes


@dataclass(frozen=True)
class Progress:
    """The project's two totals, in seconds of video, and what is missing."""

    done_seconds: float = 0.0
    remaining_seconds: float = 0.0
    #: Project videos with no recorded running time, so in neither total above.
    unmeasured: int = 0

    @property
    def percent(self) -> int | None:
        """How much of what it can see is done — ``None`` when it sees nothing.

        None rather than 0 because the two are worth telling apart: a library
        whose running times have not been recorded yet has no answer, where a
        library with nothing upscaled has the answer zero.
        """
        total = self.done_seconds + self.remaining_seconds
        return None if total <= 0 else round(self.done_seconds / total * 100)


def so_far(queued: Iterable[Path]) -> Progress:
    """What the project has behind it and ahead of it.

    *queued* is the queue as the stage just collected it.  Passed in rather than
    gathered again: collecting it opens three files and walks every bucket, and
    the stage is holding the answer already.
    """
    done_seconds, unmeasured = _total(_upscaled().values())
    remaining_seconds, still_unmeasured = _total(_recorded_duration(video)
                                                 for video in queued)
    return Progress(done_seconds, remaining_seconds, unmeasured + still_unmeasured)


def _total(durations: Iterable[float | None]) -> tuple[float, int]:
    """The running times that are known, added up, and a count of the ones not."""
    total, unmeasured = 0.0, 0
    for seconds in durations:
        if seconds is None:
            unmeasured += 1
        else:
            total += seconds
    return total, unmeasured


def _upscaled() -> dict[str, float | None]:
    """Each original the library already holds an upscale of, and how long it ran.

    Keyed by the *original's* stem rather than the variant's, because one
    original can have several variants — a second recipe, or a version saved
    under a name of its own (``config.NONAI_VERSION_OVERRIDES``) — and it is one
    video's worth of the project either way.  The variant's own running time
    answers for the original's: the recipe interpolates frames rather than
    changing the length, which is the same equality the stage checks an encode's
    completeness against.
    """
    found: dict[str, float | None] = {}
    for bucket in buckets():
        for video in sorted(bucket.rglob("*")):
            if not is_finalized_video_file(video, config.VIDEO_EXTENSIONS):
                continue
            if not is_processed_stem(video.stem):
                continue
            original = strip_processing_suffixes(video.stem)
            if found.get(original) is None:
                found[original] = _recorded_duration(video)
    return found


def _recorded_duration(video: Path) -> float | None:
    return video_type.duration_of(sidecar.read(sidecar.sidecar_path(video)))
