"""What the upscale queue window is handed, and the five words for the one in flight.

The shape only. :mod:`tasks.nonai_lineup` fills it in from the library and the
stage's own records, and ``gui/queue_window.py`` draws it -- which is why the
shape lives here rather than beside either: the window layer reaches the stages
through ``evolver`` alone (tests/test_layering.py), and a vocabulary both ends
spell has to be one declaration or it is two that drift.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class Entry:
    """One video waiting its turn, as the window lists it."""

    #: Its path within the non-AI library, which is what the window hands back
    #: when the queue is rearranged or this video is asked for now.
    video: str
    name: str
    seconds: float | None
    pinned: bool = False


@dataclass(frozen=True)
class Now:
    """The one video the machine is on, and how far it has got."""

    entry: Entry
    state: str
    percent: int | None = None
    #: What is keeping a video asked for from starting, in the stage's word for
    #: it -- "low_ram", "topaz_busy" and the rest of ``StartAttempt.deferred``.
    held_back: str = ""


@dataclass(frozen=True)
class Lineup:
    now: Now | None
    up_next: tuple[Entry, ...]
