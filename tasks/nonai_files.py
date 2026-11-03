from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_queue

stage_lock = threading.Lock()


@dataclass(frozen=True)
class StageFiles:
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
        return cls(
            job=job or config.NONAI_JOB_STATE_FILE,
            attempts=attempts or config.NONAI_ATTEMPTS_FILE,
            cooldown=cooldown or config.NONAI_COOLDOWN_FILE,
            skip_list=skip_list or config.NONAI_SKIP_LIST,
            pin_list=pin_list or config.NONAI_PIN_LIST,
            watch_stats=watch_stats or config.FUN_TIME_WATCH_STATS_FILE,
            request=request or config.NONAI_REQUEST_FILE,
        )

    def queued_videos(self) -> list[nonai_queue.QueuedVideo]:
        return nonai_queue.collect_queued_videos(
            skip_list=self.skip_list, pin_list=self.pin_list, watch_stats_file=self.watch_stats)
