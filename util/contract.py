from __future__ import annotations

import json
from pathlib import Path

import config
from util import library_records, warm_gun
from util.media_files import PARTIAL_MARKER

CONTRACT_FILE = "evolver_contract.json"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def library_relative() -> dict[str, str]:
    return {
        "inbox_dir": _under_library(config.INBOX_DIR),
        "upscaled_dir": _under_library(config.OUT_UPSCALED_DIR),
    }


def _under_library(path: Path) -> str:
    return path.relative_to(config.LIBRARY_ROOT).as_posix()


def declaration() -> dict:
    return {
        "library_relative": library_relative(),
        "partial_marker": PARTIAL_MARKER,
        "library_record": {"folder": _under_library(config.METADATA_DIR),
                           **library_records.declaration()},
        "journals": {"fields": list(warm_gun.FIELDS),
                     "favorite_events": list(warm_gun.FAVORITE_EVENTS),
                     "act_event": warm_gun.ACT_EVENT, "act_field": warm_gun.ACT_FIELD},
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
