"""Persistent settings for the tray application."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import config

log = logging.getLogger(__name__)


@dataclass
class EvolverSettings:
    interval_minutes: int = 10
    enable_toasts: bool = False
    # A one-time opt-in, off by default because a non-AI encode owns the GPU
    # for hours. Once on, Evolver auto-manages it by user presence — running it
    # while idle, suspending it the moment the user returns.
    nonai_upscale_enabled: bool = False

    def save(self, path: Path | None = None):
        path = path or config.GUI_SETTINGS_FILE
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> EvolverSettings:
        path = path or config.GUI_SETTINGS_FILE
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            settings = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            # Say so first: falling back silently is how one malformed byte
            # becomes "my interval went back to ten and I do not know why",
            # and the next save writes the evidence away.
            log.warning("Could not read settings from %s; using the defaults.",
                        path, exc_info=True)
            return cls()
        # The dialog's spin box cannot go below 1, but this file is plain JSON
        # in the project folder: a hand-edited 0 reaches the scheduler's
        # clock alignment, which divides by it.
        settings.interval_minutes = max(settings.interval_minutes, 1)
        return settings
