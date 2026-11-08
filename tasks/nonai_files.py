from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import config
from tasks import nonai_queue

run_poll_and_window_lock = threading.Lock()


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
    def configured(cls, **given: Path | None) -> StageFiles:
        defaults = {
            "job": config.NONAI_JOB_STATE_FILE,
            "attempts": config.NONAI_ATTEMPTS_FILE,
            "cooldown": config.NONAI_COOLDOWN_FILE,
            "skip_list": config.NONAI_SKIP_LIST,
            "pin_list": config.NONAI_PIN_LIST,
            "watch_stats": config.FUN_TIME_WATCH_STATS_FILE,
            "request": config.NONAI_REQUEST_FILE,
        }
        unknown = given.keys() - defaults.keys()
        if unknown:
            raise TypeError(f"unknown stage file: {', '.join(sorted(unknown))}")
        return cls(**{name: given.get(name) or default for name, default in defaults.items()})

    def queued_videos(self) -> list[nonai_queue.QueuedVideo]:
        return nonai_queue.collect_queued_videos(
            skip_list=self.skip_list, pin_list=self.pin_list, watch_stats_file=self.watch_stats)
