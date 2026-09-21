"""What another app must know about this one, published for it.

Two arrangements, each of which every other side had written out for itself
from reading this repo's source, with nothing comparing the copies.
Origenerator sends a finished video here by copying it into the inbox under a
folder named for its lane, and later reads the upscale back out of the outbox;
Fun Time reads the record this repo keeps beside every library video, and
writes one field of it back.  A folder renamed here left that app dropping
clips where nothing ingests them; a key renamed here left that reader quietly
answering "nothing recorded"; both suites stayed green through either (audit
cross/boundaries/cross/003).

``evolver_contract.json`` at the checkout root is how the promise travels.  Run
``python -m util.contract`` to rewrite it; the suite fails on a copy that no
longer matches.

Every path is relative to the library root, never absolute: that root is
private, and each app resolves it from its own content overlay.  The folder a
lane's clips arrive under is not here either, for the same reason -- it is
library vocabulary, and both apps read it from their overlays.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
from util import library_records
from util.media_files import PARTIAL_MARKER

#: At the checkout root beside the launcher, which is the path an app that
#: resolves this checkout at all already has.
CONTRACT_FILE = "evolver_contract.json"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def library_relative() -> dict[str, str]:
    """The two folders a sender meets, as posix paths under the library root."""
    return {
        "inbox_dir": _under_library(config.INBOX_DIR),
        "upscaled_dir": _under_library(config.OUT_UPSCALED_DIR),
    }


def _under_library(path: Path) -> str:
    return path.relative_to(config.LIBRARY_ROOT).as_posix()


def declaration() -> dict:
    """The published document, as another app reads it."""
    return {
        "library_relative": library_relative(),
        "partial_marker": PARTIAL_MARKER,
        "library_record": library_records.declaration(),
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    """Write the document out, in the shape the tracked copy holds."""
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
