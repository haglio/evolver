from __future__ import annotations

from dataclasses import dataclass

NEXT = "next"
UPSCALING = "upscaling"
PAUSED = "paused"
ASKED_FOR = "asked_for"
STARTING = "starting"
FINISHING = "finishing"

_RUNS_NOW = {ASKED_FOR, STARTING}


@dataclass(frozen=True)
class Entry:
    video: str
    name: str
    seconds: float | None
    pinned: bool = False


@dataclass(frozen=True)
class Head:
    state: str
    percent: int | None = None
    held_back: str = ""

    @property
    def runs_now(self) -> bool:
        return self.state in _RUNS_NOW

    @property
    def in_flight(self) -> bool:
        return self.state != NEXT


@dataclass(frozen=True)
class UpscaleQueue:
    rows: tuple[Entry, ...]
    head: Head | None
