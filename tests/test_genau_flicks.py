from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app_support.flick_folder import ai_flicks_in, non_ai_flicks_in

from tasks import genau_deliver, upscale
from tests.gallery_fakes import FakeGallery
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
from util import lanes, sidecar, topaz

GENAU_SOURCE = "example-loop-clips"


def _encode(in_file, tmp, _env, settings=None, **kwargs):
    topaz.command(in_file, tmp, settings)
    tmp.write_text(f"upscaled with {settings.name}", encoding="utf-8")
    return True


@contextmanager
def _genau(size=(1260, 700)):
    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config(genau_source=GENAU_SOURCE, ORIGENERATOR_DB_PATH=root / "no gallery.db"), \
             patch("tasks.upscale._run_ffmpeg", side_effect=_encode) as encode, \
             patch("tasks.upscale.ffprobe.video_dimensions", return_value=size), \
             patch("tasks.upscale.ffprobe.frame_rate", return_value=None), \
             patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            lib.encode = encode
            yield lib


def _cut(lib: LaneLibrary, stem="flick one"):
    return touch_video(non_ai_flicks_in(lib.genau_flicks) / f"{stem}.mp4")


def _run(lib: LaneLibrary):
    upscale.run(gallery=FakeGallery(), low_disk=upscale.LowDiskWarning.configured(floor_gb=1))
    genau_deliver.run()


class TestAFlickGenaumacherCut(unittest.TestCase):
    def test_is_upscaled_in_its_place_where_genau_plays_it(self):
        with _genau() as lib:
            cut = _cut(lib)

            _run(lib)

            assert sorted(path.name for path in cut.parent.iterdir()) == ["flick one_topaz.mp4"]
            assert (cut.parent / "flick one_topaz.mp4").read_text(encoding="utf-8") == \
                f"upscaled with {topaz.GENAU_FLICK_UPSCALE.name}"

    def test_takes_its_favorite_its_sound_and_its_place_in_the_order_along(self):
        with _genau() as lib:
            cut = _cut(lib)
            sidecar.update(sidecar.sidecar_path(cut), lambda _: {"favorite": True, "id": "made-up-id"})
            touch_video(lanes.genau_sound_of(cut))
            os.utime(cut, (1_700_000_000, 1_700_000_000))

            _run(lib)

            upscaled = cut.with_name("flick one_topaz.mp4")
            assert sidecar.read(sidecar.sidecar_path(upscaled)) == {"favorite": True, "id": "made-up-id"}
            assert not sidecar.sidecar_path(cut).exists()
            assert sorted(p.name for p in lib.genau_audio.iterdir()) == ["flick one_topaz.mp3"]
            assert upscaled.stat().st_mtime == 1_700_000_000

    def test_one_whose_size_cannot_be_read_is_left_for_a_later_run(self):
        with _genau(size=None) as lib:
            cut = _cut(lib)

            result = upscale.run(gallery=FakeGallery(), low_disk=upscale.LowDiskWarning.configured(floor_gb=1))

            assert (result.processed, result.failed) == (0, 1)
            assert cut.is_file()

    def test_one_already_enhanced_is_left_as_it_is(self):
        with _genau() as lib:
            touch_video(non_ai_flicks_in(lib.genau_flicks) / "flick one_iris2.mp4")

            _run(lib)

            lib.encode.assert_not_called()


class TestAnAiFlickThatReachedGenauBeforeItsUpscale(unittest.TestCase):
    def test_is_upscaled_as_every_ai_flick_is_in_its_place(self):
        with _genau() as lib:
            old = touch_video(ai_flicks_in(lib.genau_flicks) / "loop one.mp4")

            _run(lib)

            assert sorted(path.name for path in old.parent.iterdir()) == ["loop one_topaz.mp4"]
            assert (old.parent / "loop one_topaz.mp4").read_text(encoding="utf-8") ==                 f"upscaled with {topaz.AI_UPSCALE_ORIGENERATOR.name}"


class TestAnOriginalLeftBesideItsUpscale(unittest.TestCase):
    def test_is_retired_by_the_genau_delivery(self):
        with _genau() as lib:
            cut = _cut(lib)
            upscaled = touch_video(cut.with_name("flick one_topaz.mp4"))

            result = genau_deliver.run()

            assert result.delivered == 1
            assert not cut.exists()
            assert upscaled.is_file()


if __name__ == "__main__":
    unittest.main()
