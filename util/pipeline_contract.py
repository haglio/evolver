"""What an app handing clips to this pipeline must know, published for it.

Origenerator sends a finished video here by copying it into the inbox under a
folder named for its lane, and later reads the upscale this pipeline made of it
back out of the outbox.  It cannot import this repo -- no app here reaches into
another's -- so it had both folders and the marker a half-written copy wears
spelled on its own side, from reading this one's source.

Spelled over there they were a copy, and nothing compared the two: renaming a
folder here left that app dropping clips where nothing ingests them, with both
suites green.  Spelled here they are the promise this repo makes, and
``evolver_contract.json`` at the checkout root is how they travel.  Run
``python -m util.pipeline_contract`` to rewrite it; the suite fails on a copy
that no longer matches.

Every path is relative to the library root, never absolute: that root is
private, and each app resolves it from its own content overlay.  The folder a
lane's clips arrive under is not here either, for the same reason -- it is
library vocabulary, and both apps read it from their overlays.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
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
    return path.relative_to(config.BASE_DIR).as_posix()


def declaration() -> dict:
    """The published document, as a sender reads it."""
    return {
        "library_relative": library_relative(),
        "partial_marker": PARTIAL_MARKER,
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
