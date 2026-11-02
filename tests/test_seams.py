"""The seams the first audit cut and the second found regrown (item 74), each held
by a ceiling that only comes down.

The tray app had been cut to its wiring and grew back to 43 methods, and the
non-AI upscale stage from 427 lines to 665, because every feature since was
written onto them beside the module that already stood for its part. A number
here fails the build before that happens again: the next feature gives its
glue a controller or a module of its own, or moves it onto the collaborator
that exists, rather than growing either of these.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT

pytestmark = pytest.mark.repo_check

NONAI_UPSCALE_LINES_AT_MOST = 359


def test_the_upscale_stage_file_is_no_longer_than_its_ceiling():
    lines = Path(PROJECT_ROOT, "tasks/nonai_upscale.py").read_text(encoding="utf-8").count("\n")

    assert lines <= NONAI_UPSCALE_LINES_AT_MOST, (
        f"tasks/nonai_upscale.py is {lines} lines, over its ceiling of "
        f"{NONAI_UPSCALE_LINES_AT_MOST}: what the stage needs that is not the stage "
        "(the encode, the queue, the files, the video asked for, the progress) has a "
        "module of its own beside it; lower the ceiling when lines leave"
    )
