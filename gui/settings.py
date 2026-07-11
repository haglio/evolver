"""Persistent settings for the tray application."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config


@dataclass
class EvolverSettings:
    interval_minutes: int = 10
    start_with_windows: bool = False
    enable_toasts: bool = False
    # Off by default: a non-AI encode monopolizes the GPU for hours, so the
    # user opts in from the tray menu when stepping away from the machine.
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
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()
