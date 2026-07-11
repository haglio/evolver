"""The shape of the 2D/non_AI library both non-AI stages walk.

A bucket is a top-level folder like ``larkin`` or ``other`` — except the ones
config excludes (``actually_AI_but_funscripted`` holds AI-pipeline outputs).
"""

from __future__ import annotations

from pathlib import Path

import config


def buckets() -> list[Path]:
    if not config.NON_AI_DIR.is_dir():
        return []
    return [
        child
        for child in sorted(config.NON_AI_DIR.iterdir())
        if child.is_dir() and child.name not in config.NONAI_EXCLUDED_BUCKETS
    ]
