from __future__ import annotations

import json
from pathlib import Path

import config
from util import library_records, warm_gun
from util.media_files import PARTIAL_MARKER

CONTRACT_FILE = "evolver_contract.json"

_THE_CHECKOUT_EVERY_READER_ALREADY_FINDS = Path(__file__).resolve().parent.parent


def library_relative() -> dict[str, str]:
    return {"inbox_dir": _relative_to_the_private_library_root(config.INBOX_DIR)}


def _relative_to_the_private_library_root(path: Path) -> str:
    return path.relative_to(config.LIBRARY_ROOT).as_posix()


def what_origenerator_and_fun_time_read() -> dict:
    return {
        "library_relative": library_relative(),
        "partial_marker": PARTIAL_MARKER,
        "library_record": {"folder": _relative_to_the_private_library_root(config.METADATA_DIR),
                           **library_records.declaration()},
        "journals": {"fields": list(warm_gun.FIELDS),
                     "favorite_events": list(warm_gun.FAVORITE_EVENTS)},
    }


def published_text() -> str:
    return json.dumps(what_origenerator_and_fun_time_read(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else _THE_CHECKOUT_EVERY_READER_ALREADY_FINDS) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
