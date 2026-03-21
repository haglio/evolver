from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


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
