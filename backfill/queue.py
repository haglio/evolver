"""Which clips still need an action, and the order the backfill tool asks about them."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from pathlib import Path

import config
from util import orientation
from util.media_files import library_videos
from util.sidecar import action_of, read, sidecar_path, wrong_action_of

# Portrait first, and that is not cosmetic: it is the order the tool asks a
# human about, and most of the unlabeled queue is portrait.
_ORIENTATIONS = (orientation.PORTRAIT, orientation.LANDSCAPE)

# Sources the scrape stage already has a metadata strategy for (see
# :mod:`tasks.prompt_scrape`): Provider from its website, Origenerator from its gallery
# database.  Every other source arrives with no upstream record of what it shows, so
# its act is the one a human has to dictate.
SCRAPED_SOURCES = frozenset({"provider", "origenerator"})


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


def unlabeled_videos() -> list[Path]:
    """Every upscaled clip whose sidecar records no ``video.action``.

    The ones a viewer *rejected* come first.  Fun Time's "wrong action" empties
    ``video.action`` and leaves ``video.wrong_action`` behind, which says a
    person just looked at that clip and told us its label was wrong: they are
    owed an answer now, not at whatever depth of the library walk the clip
    happens to sit at.  For the same reason a rejection overrides the
    scraped-source skip below — the scrape's claim about the clip is the very
    thing being contradicted, and re-running the scrape would only assert it
    again.
    """
    rejected: list[Path] = []
    never_labeled: list[Path] = []
    for source, video in iter_library_videos():
        payload = read(sidecar_path(video))
        if action_of(payload):
            continue
        if wrong_action_of(payload):
            rejected.append(video)
        elif source not in SCRAPED_SOURCES:
            never_labeled.append(video)
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

    def __init__(self, videos: list[Path]) -> None:
        self._pending = deque(videos)

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
