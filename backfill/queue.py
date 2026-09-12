"""Which clips still need an action, and the order the backfill tool asks about them."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes, orientation, sidecar
from util.media_files import library_videos
from util.sidecar import action_of, sidecar_path, wrong_action_of
from util.variants import sorted_stem_of

# Portrait first, and that is not cosmetic: it is the order the tool asks a
# human about, and most of the unlabeled queue is portrait.
_ORIENTATIONS = (orientation.PORTRAIT, orientation.LANDSCAPE)


def scraped_sources() -> frozenset[str]:
    """Sources the scrape stage already has a metadata strategy for (see
    :mod:`tasks.prompt_scrape`): the provider from its website, Origenerator from
    its gallery database.  Every other source arrives with no upstream record of
    what it shows, so its act is the one a human has to dictate.

    Read at the call rather than at import: the provider's name is the
    overlay's, and a literal agreed with it only by happening to.
    """
    return frozenset({config.PROVIDER_SOURCE, lanes.ORIGENERATOR_SOURCE})


def iter_library_videos() -> Iterator[tuple[str, Path]]:
    """Every finalized upscaled clip as ``(source name, path)``, both orientations.

    Walked in a stable order — orientation, then source, then filename — so both
    the work queue and the example-clip scan see clips the same way each run.
    """
    for orient in _ORIENTATIONS:
        orient_dir = config.OUT_UPSCALED_DIR / orient
        if not orient_dir.is_dir():
            continue
        for source_dir in sorted(p for p in orient_dir.iterdir() if p.is_dir()):
            for video in sorted(library_videos(source_dir)):
                yield source_dir.name, video


@dataclass(frozen=True)
class ScannedClip:
    """One library clip, as the tool's two startup passes read it."""

    source: str
    path: Path
    action: str
    wrong_action: str
    clip_id: str


def library_scan() -> list[ScannedClip]:
    """Every upscaled clip, walked once and its sidecar parsed once.

    Startup wants two different projections of the same data -- the clips with
    no action, and the first clip per action plus an index by clip id -- and
    used to take a full walk and a full sidecar read for each. On a library of
    thousands, that is a tray-launched tool sitting with no window on screen
    for twice as long as it needs to.

    In ``iter_library_videos``' order, which is what lets a reopened session
    resume where it left off: it is not re-sorted here, and must not be.
    """
    return [
        ScannedClip(
            source=source,
            path=video,
            action=action_of(payload),
            wrong_action=wrong_action_of(payload),
            clip_id=sorted_stem_of(video.stem),
        )
        for source, video in iter_library_videos()
        if (payload := sidecar.read(sidecar_path(video))) is not None
    ]


def unlabeled_clips(scan: list[ScannedClip] | None = None) -> list[Path]:
    """Every upscaled clip whose sidecar records no ``video.action``.

    The ones a viewer *rejected* come first.  Fun Time's "wrong action" empties
    ``video.action`` and leaves ``video.wrong_action`` in its place, which says a
    person just looked at that clip and told us its label was wrong: they are
    owed an answer now, not at whatever depth of the library walk the clip
    happens to sit at.  For the same reason a rejection overrides the
    scraped-source skip below — the scrape's claim about the clip is the very
    thing being contradicted, and re-running the scrape would only assert it
    again.
    """
    scan = library_scan() if scan is None else scan
    scraped = scraped_sources()
    rejected: list[Path] = []
    never_labeled: list[Path] = []
    for clip in scan:
        if clip.action:
            continue
        if clip.wrong_action:
            rejected.append(clip.path)
        elif clip.source not in scraped:
            never_labeled.append(clip.path)
    return rejected + never_labeled


class BackfillQueue:
    """The clips awaiting an action, kept in the order they were found.

    A stable order is what lets a reopened session pick up where the last left
    off: labelled clips drop out, so the next open resumes at the first clip still
    unlabelled rather than jumping to a fresh random one.

    The clip at the front is the one on screen.  :meth:`resolve` retires it —
    it has been labelled or discarded — while :meth:`defer` sends it to the
    back, unanswered, to come round again later.

    :meth:`restore` and :meth:`undefer` are their exact inverses, so undoing a
    run of decisions back to front rewinds the queue to the order it had.
    """

    def __init__(self, clips: list[Path]) -> None:
        self._pending = deque(clips)

    @property
    def remaining(self) -> int:
        """How many clips still need an action, deferred ones included."""
        return len(self._pending)

    @property
    def current(self) -> Path | None:
        """The clip on screen, or None once every clip has been resolved."""
        return self._pending[0] if self._pending else None

    def resolve(self) -> None:
        """Retire the current clip — it has been labelled or discarded."""
        if self._pending:
            self._pending.popleft()

    def defer(self) -> None:
        """Send the current clip to the back, still needing an action."""
        if self._pending:
            self._pending.rotate(-1)

    def restore(self, clip: Path) -> None:
        """Put a resolved *clip* back on screen — the inverse of :meth:`resolve`."""
        self._pending.appendleft(clip)

    def undefer(self) -> None:
        """Bring the deferred clip back to the front — the inverse of :meth:`defer`."""
        if self._pending:
            self._pending.rotate(1)
