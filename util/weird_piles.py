from __future__ import annotations

from pathlib import Path

import config


def weird_pile_dirs() -> tuple[Path, Path]:
    return config.WEIRD_DIR, config.GENAU_WEIRD_DIR
