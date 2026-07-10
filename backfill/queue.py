"""Which clips still need an action, and the order the backfill tool asks about them."""

from __future__ import annotations

import random
from collections import deque
from pathlib import Path

import config
from util.media_files import iter_finalized_videos
from util.sidecar import action_of, read, sidecar_path

_ORIENTATIONS = ("portrait", "landscape")

# Sources the scrape stage already has a metadata strategy for (see
# :mod:`tasks.prompt_scrape`): Provider from its website, Origenerator from its gallery
# database.  Every other source arrives with no upstream record of what it shows, so
# its act is the one a human has to dictate.
SCRAPED_SOURCES = frozenset({"provider", "origenerator"})


def unlabeled_videos() -> list[Path]:
    """Every upscaled clip whose sidecar records no ``video.action``."""
    videos: list[Path] = []
    for orient in _ORIENTATIONS:
        orient_dir = config.OUT_UPSCALED_DIR / orient
        if not orient_dir.is_dir():
            continue
        for source_dir in sorted(p for p in orient_dir.iterdir() if p.is_dir()):
            if source_dir.name in SCRAPED_SOURCES:
                continue
            for video in sorted(iter_finalized_videos(source_dir, config.VIDEO_EXTENSIONS)):
                if not action_of(read(sidecar_path(video))):
                    videos.append(video)
    return videos


class BackfillQueue:
    """The clips awaiting an action, shuffled so a long session never drags.

    The clip at the front is the one on screen.  :meth:`resolve` retires it —
    it has been labelled or discarded — while :meth:`defer` sends it to the
    back, unanswered, to come round again later.

    :meth:`restore` and :meth:`undefer` are their exact inverses, so undoing a
    run of decisions back to front rewinds the queue to the order it had.
    """

    def __init__(self, videos: list[Path], rng: random.Random | None = None) -> None:
        shuffled = list(videos)
        (rng or random.Random()).shuffle(shuffled)
        self._pending = deque(shuffled)

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
