"""What the upscale queue window is handed: one list, and what its first row is doing.

The shape only. :mod:`tasks.nonai_lineup` fills it in from the library and the
stage's own records, and ``gui/queue_window.py`` draws it -- which is why the
shape lives here rather than beside either: the window layer reaches the stages
through ``evolver`` alone (tests/test_layering.py), and a vocabulary both ends
spell has to be one declaration or it is two that drift.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Nothing is in flight; the first row is simply the one the stage takes next.
NEXT = "next"
#: Upscaling, with nobody at the computer.
UPSCALING = "upscaling"
#: Frozen where it stands, because somebody is.
PAUSED = "paused"
#: Upscaling because it was asked for, whoever is at the computer.
ASKED_FOR = "asked_for"
#: Asked for, and waiting for the next run to start it.
STARTING = "starting"
#: Its encode has ended; the next run promotes the output and retires the original.
FINISHING = "finishing"

_RUNS_NOW = {ASKED_FOR, STARTING}


@dataclass(frozen=True)
class Entry:
    """One video in the queue, as the window lists it."""

    #: Its path within the non-AI library, which is what the window hands back
    #: when the queue is rearranged or this video is asked for now.
    video: str
    name: str
    seconds: float | None
    pinned: bool = False


@dataclass(frozen=True)
class Head:
    """What the first row's video is doing, and how far it has got."""

    state: str
    percent: int | None = None
    #: What is keeping a video asked for from starting, in the stage's word for
    #: it -- "low_ram", "topaz_busy" and the rest of ``StartAttempt.deferred``.
    held_back: str = ""

    @property
    def runs_now(self) -> bool:
        """Whether it goes ahead even while somebody is at the computer."""
        return self.state in _RUNS_NOW

    @property
    def in_flight(self) -> bool:
        """Whether the machine is on it, so nothing else can take its place by a drag."""
        return self.state != NEXT


@dataclass(frozen=True)
class Lineup:
    rows: tuple[Entry, ...]
    #: None only when there are no rows.
    head: Head | None
