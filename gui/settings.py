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
            log.warning("Could not read settings from %s; using the defaults.",
                        path, exc_info=True)
            return cls()
        settings.interval_minutes = max(settings.interval_minutes, 1)
        return settings
