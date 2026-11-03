from __future__ import annotations

from pathlib import Path
from typing import Any

from app_support.overlay import MissingOverlayKey, missing_keys, read_overlay

PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_CONTENT = PROJECT_DIR / "content.local.json"
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


def load_content() -> dict[str, Any]:
    return read_overlay(LOCAL_CONTENT, EXAMPLE_CONTENT)


def refuse_an_incomplete_overlay() -> None:
    if missing := missing_keys(LOCAL_CONTENT, EXAMPLE_CONTENT):
        raise MissingOverlayKey((", ".join(missing),), LOCAL_CONTENT)
