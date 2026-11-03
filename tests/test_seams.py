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
