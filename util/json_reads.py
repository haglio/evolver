from __future__ import annotations

import json
from pathlib import Path


def read_dict(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_dict_strict(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
