from __future__ import annotations

import shutil
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import config


ROOT = Path(__file__).resolve().parent.parent / ".tmp-test" / "unittest"


@contextmanager
def workspace_temp_dir():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def override_config(**overrides):
    """Temporarily override config module attributes with auto-restore."""
    with ExitStack() as stack:
        for key, value in overrides.items():
            stack.enter_context(patch.object(config, key, value))
        yield
