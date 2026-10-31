"""The files the non-AI upscale stage touches, resolved once at its boundary, and
the lock everything that touches them shares."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_queue

#: The pipeline tick (the worker thread), the presence poll (the GUI thread) and
#: the queue window's asks (its background thread) all touch the one job record
#: and its ffmpeg; this keeps a suspend, a resume or a stop from racing a tick.
stage_lock = threading.Lock()


@dataclass(frozen=True)
class StageFiles:
    """Four the stage writes -- the job record, the attempt counter, the cooldown
    stamp, the request from the queue window -- and three the queue reads: the
    skip and pin lists, and Fun Time's watch stats."""

    job: Path
    attempts: Path
    cooldown: Path
    skip_list: Path
    pin_list: Path
    watch_stats: Path
    request: Path

    @classmethod
    def configured(cls, *, job: Path | None = None, attempts: Path | None = None,
                   cooldown: Path | None = None, skip_list: Path | None = None,
                   pin_list: Path | None = None, watch_stats: Path | None = None,
                   request: Path | None = None) -> StageFiles:
        """Each path given, or the configured one where none was.

        Read from ``config`` here rather than as signature defaults: a default
        is evaluated at import, which would put the value out of reach of
        ``override_config``, the seam every stage test steers with.
        """
        return cls(
            job=job or config.NONAI_JOB_STATE_FILE,
            attempts=attempts or config.NONAI_ATTEMPTS_FILE,
            cooldown=cooldown or config.NONAI_COOLDOWN_FILE,
            skip_list=skip_list or config.NONAI_SKIP_LIST,
            pin_list=pin_list or config.NONAI_PIN_LIST,
            watch_stats=watch_stats or config.FUN_TIME_WATCH_STATS_FILE,
            request=request or config.NONAI_REQUEST_FILE,
        )

    def candidates(self) -> list[nonai_queue.Candidate]:
        """The queue as it stands: every unprocessed video, most wanted first."""
        return nonai_queue.collect_candidates(
            skip_list=self.skip_list, pin_list=self.pin_list, watch_stats_file=self.watch_stats)
