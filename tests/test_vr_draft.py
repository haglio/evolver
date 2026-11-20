from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tasks import vr_draft


class FakeRun:
    def __init__(self, *codes: int) -> None:
        self.codes = list(codes)
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], **how):
        self.ran.append(command)
        return SimpleNamespace(returncode=self.codes.pop(0))


def test_the_video_is_flattened_to_one_eye_before_goblinscript_drafts_the_flat_copy(tmp_path):
    run = FakeRun(0, 0)
    flat = tmp_path / "flat" / "video one_180.mp4"

    code = vr_draft.main([str(tmp_path / "video one_180.mp4"), str(flat), "--", "goblin", "draft", str(flat)],
                         run=run)

    assert code == 0
    assert run.ran == [vr_draft.flatten_command(tmp_path / "video one_180.mp4", flat), ["goblin", "draft", str(flat)]]
    assert flat.parent.is_dir()


def test_goblinscript_is_not_started_when_flattening_fails(tmp_path):
    run = FakeRun(1)

    code = vr_draft.main([str(tmp_path / "video one.mp4"), str(tmp_path / "flat.mp4"), "--", "goblin"], run=run)

    assert (code, len(run.ran)) == (1, 1)


@pytest.mark.parametrize(("name", "lens"), [
    ("video one_MKX200.mp4", "v360=input=fisheye:output=flat:ih_fov=200"),
    ("video one_FISHEYE190.mp4", "v360=input=fisheye:output=flat:ih_fov=190"),
    ("video one_RF52.mp4", "v360=input=fisheye:output=flat:ih_fov=190"),
    ("video one_360.mp4", "v360=input=equirect"),
    ("video one_180.mp4", "v360=input=hequirect"),
])
def test_the_lens_is_read_from_the_videos_name(name, lens):
    view = vr_draft.flatten_command(Path(name), Path("flat.mp4"))[10]

    assert lens in view
    assert view.startswith("fps=30")
    assert "pitch=-29.3580" in view
    assert ("crop=iw/2" in view) == ("_360" not in name)
