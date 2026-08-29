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


def make_run_record(**overrides):
    """A RunRecord with every field defaulted to an invented value.

    Five test classes each built the same seven fields by hand, three of
    them repeating identical literal timestamps -- so adding a RunRecord
    field meant editing five places. All values are fabricated, per this
    repo's fixture rule.
    """
    from gui.run_record import RunRecord

    fields = dict(
        id="2026-07-25T15-20-02",
        started_at="2026-07-25T15:20:02",
        finished_at="2026-07-25T15:20:02",
        duration_seconds=12.0,
        trigger="scheduled",
        status="success",
        stages=[],
    )
    fields.update(overrides)
    return RunRecord(**fields)
