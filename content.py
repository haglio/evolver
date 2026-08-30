"""Content overlay — the copy that must not be published, loaded at runtime.

Everything here describes the machine and the library rather than the app: the
library root, the browser profile, the folder Origenerator drops Genau clips
in, the scraped provider, and the spoken act vocabulary. All of it lives in
``content.local.json`` (git-ignored) rather than in source; the committed
``content.example.json`` documents every key and is what a fresh or public
checkout loads, so ``config``, the recognizer, the grid and the tests all
behave the same either way.

The act vocabulary is where the content/logic line is easiest to see: the
phrases a viewer says and the ``video.action`` strings they record describe the
library, while everything else about the vocabulary — the camera words, the
controls, how phrases are combined — is logic and stays in the module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_CONTENT = PROJECT_DIR / "content.local.json"
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


def load_content(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> dict[str, Any]:
    """The local overlay's content when present, else the committed example.

    The defaults are resolved on each call rather than bound at import, so the
    test suite can point every consumer at the example overlay (see
    ``tests/__init__.py``) and behave exactly as a public checkout would.
    """
    local_path = LOCAL_CONTENT if local_path is None else local_path
    example_path = EXAMPLE_CONTENT if example_path is None else example_path
    path = local_path if local_path.exists() else example_path
    return json.loads(path.read_text(encoding="utf-8"))
