from __future__ import annotations

import dataclasses
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import check_correspondence
import config
from tasks import genau_deliver, sort, upscale
from tests.gallery_fakes import GalleryOnDisk, a_gallery_of, kept_at
from tests.temp_helpers import (
    LaneLibrary,
    gallery_of_videos_made_again,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import lanes, provenance, sidecar

GENAU_SOURCE = "example-loop-clips"


@contextmanager
def _genau_lane(**extra):
    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config(genau_source=GENAU_SOURCE, ORIGENERATOR_DB_PATH=root / "no gallery.db",
                        **extra):
            yield lib


def _upscaled(lib: LaneLibrary, stem="loop_1", orient="landscape", contents="upscaled"):
    original = touch_video(lib.sorted_dir / GENAU_SOURCE / orient / f"{stem}.mp4")
    flick = lanes.upscale_of(GENAU_SOURCE, orient, stem)
    flick.parent.mkdir(parents=True, exist_ok=True)
    flick.write_text(contents, encoding="utf-8")
    return flick, original


class TestFinishingAGenauUpscale(unittest.TestCase):
    def test_the_upscale_stays_where_genau_plays_it_and_its_sorted_copy_is_retired(self):
        with _genau_lane() as lib:
            flick, original = _upscaled(lib)

            result = genau_deliver.run()

            assert result.delivered == 1
            assert flick == lib.genau_flicks / "2D" / "AI" / "loop_1_topaz.mp4"
            assert flick.read_text(encoding="utf-8") == "upscaled"
            assert not original.exists()

    def test_a_finished_flick_leaves_the_correspondence_check_satisfied(self):
        with _genau_lane() as lib:
            _upscaled(lib)

            genau_deliver.run()

            assert check_correspondence.run().ok

    def test_a_finished_flick_is_not_upscaled_again(self):
        with _genau_lane() as lib:
            _upscaled(lib)

            genau_deliver.run()

            assert upscale.collect_queued_videos(upscale.UpscaleFolders.configured()) == []

    def test_a_delivered_flick_is_given_no_sidecar_since_the_gallery_is_its_record(self):
        with _genau_lane() as lib:
            flick, _original = _upscaled(lib)

            result = genau_deliver.run()

            assert result.delivered == 1
            assert not sidecar.sidecar_path(flick).exists()
            assert not lib.metadata.exists()

    def test_a_loop_with_sound_leaves_its_sound_where_genau_plays_sound_from(self):
        saved = []
        with _genau_lane() as lib, \
             patch("tasks.genau_deliver.has_sound", return_value=True), \
             patch("tasks.genau_deliver.save_as_mp3",
                   side_effect=lambda video, mp3: saved.append((video, mp3))):
            flick, _original = _upscaled(lib)

            genau_deliver.run()

            assert saved == [(flick, lib.genau_audio / "loop_1_topaz.mp3")]

    def test_a_silent_loop_leaves_no_sound_behind(self):
        with _genau_lane() as lib, \
             patch("tasks.genau_deliver.has_sound", return_value=False), \
             patch("tasks.genau_deliver.save_as_mp3") as save:
            _upscaled(lib)

            result = genau_deliver.run()

            assert result.delivered == 1
            save.assert_not_called()

    def test_a_sound_that_cannot_be_saved_leaves_the_loop_finished(self):
        with _genau_lane() as lib, \
             patch("tasks.genau_deliver.has_sound", return_value=True), \
             patch("tasks.genau_deliver.save_as_mp3", side_effect=OSError("disk full")), \
             self.assertLogs("tasks.genau_deliver", level="WARNING"):
            flick, original = _upscaled(lib)

            result = genau_deliver.run()

            assert (result.delivered, result.failed) == (1, 0)
            assert flick.is_file()
            assert not original.exists()

    def test_kinos_upscales_are_left_as_they_are(self):
        with _genau_lane() as lib:
            _upscaled(lib)
            kino_original = touch_video(lib.sorted_dir / "origenerator" / "landscape" / "video_1.mp4")
            kino = touch_video(lanes.upscale_of("origenerator", "landscape", "video_1"))

            result = genau_deliver.run()

            assert result.delivered == 1
            assert kino.is_file()
            assert kino_original.is_file()

    def test_flicks_sorted_under_either_orientation_are_finished(self):
        with _genau_lane() as lib:
            _wide, wide_original = _upscaled(lib, stem="wide", orient="landscape")
            _tall, tall_original = _upscaled(lib, stem="tall", orient="portrait")

            result = genau_deliver.run()

            assert result.delivered == 2
            assert not wide_original.exists()
            assert not tall_original.exists()

    def test_a_flick_still_waiting_for_its_upscale_keeps_its_sorted_copy(self):
        with _genau_lane() as lib:
            flick, original = _upscaled(lib)
            a_gallery_of(config.ORIGENERATOR_DB_PATH, [kept_at(
                "made-1", flick, upscale_provenance=json.dumps(provenance.reconstructed(None)))])

            result = genau_deliver.run()

            assert result.delivered == 0
            assert original.is_file()

    def test_a_sorted_copy_that_cannot_be_retired_is_left_for_the_next_run(self):
        with _genau_lane() as lib:
            flick, original = _upscaled(lib)

            def _locked(self, missing_ok=False):
                raise OSError("the file is in use")

            with patch.object(type(original), "unlink", _locked):
                result = genau_deliver.run()

            assert (result.delivered, result.failed) == (0, 1)
            assert flick.is_file()
            assert original.is_file()

    def test_an_empty_lane_is_a_no_op(self):
        with _genau_lane():
            result = genau_deliver.run()

            assert (result.delivered, result.failed) == (0, 0)


class TestAFlickMadeAgain(unittest.TestCase):
    def _remade(self, lib: LaneLibrary, handed_over: str) -> None:
        touch_video(lib.inbox / GENAU_SOURCE / handed_over).write_text("remade", encoding="utf-8")

        def encode(_in_file, tmp, _env, _settings=None, **kwargs):
            tmp.write_text("upscaled again", encoding="utf-8")
            return True

        with patch("tasks.sort.orientation_of", return_value="landscape"), \
             patch("tasks.upscale._run_ffmpeg", side_effect=encode), \
             patch("tasks.upscale.ffprobe.frame_rate", return_value=None), \
             patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            sort.run(gallery=GalleryOnDisk(config.ORIGENERATOR_DB_PATH))
            upscale.run(gallery=GalleryOnDisk(config.ORIGENERATOR_DB_PATH), max_items=5, low_disk=upscale.LowDiskWarning.configured(floor_gb=1))
            genau_deliver.run()

    def test_it_takes_the_place_of_the_one_genau_plays_and_keeps_its_record(self):
        with workspace_temp_dir() as root:
            gallery = gallery_of_videos_made_again(root / "gallery.db", ["loop_1.mp4"])
            lib = LaneLibrary(root)
            with lib.config(genau_source=GENAU_SOURCE, ORIGENERATOR_DB_PATH=gallery):
                played = lanes.upscale_of(GENAU_SOURCE, "landscape", "loop_1")
                touch_video(played).write_text("the flick first made", encoding="utf-8")
                os.utime(played, (1_700_000_000, 1_700_000_000))
                write_sidecar(sidecar.sidecar_path(played), {"favorite": True, "genau": {"flipped": True}})

                self._remade(lib, "loop_1.mp4")

                record = sidecar.read(sidecar.sidecar_path(played))
            assert sorted(path.name for path in played.parent.iterdir()) == [played.name]
            assert played.read_text(encoding="utf-8") == "upscaled again"
            assert played.stat().st_mtime == 1700000001
            assert (record["favorite"], record["genau"]) == (True, {"flipped": True})
            assert not list((lib.sorted_dir / GENAU_SOURCE).rglob("*.mp4"))

    def test_under_a_new_name_it_takes_the_place_of_the_one_under_the_old(self):
        with workspace_temp_dir() as root:
            gallery = gallery_of_videos_made_again(root / "gallery.db", ["loop_1-audio.mp4"])
            lib = LaneLibrary(root)
            with lib.config(genau_source=GENAU_SOURCE, ORIGENERATOR_DB_PATH=gallery):
                played = lib.genau_flicks / "2D" / "AI" / "loop_1__topaz.mp4"
                touch_video(played).write_text("the flick first made", encoding="utf-8")
                its_sound = touch_video(lib.genau_audio / "loop_1__topaz.mp3")
                write_sidecar(sidecar.sidecar_path(played), {"favorite": True})

                self._remade(lib, "loop_1-audio.mp4")

                remade = played.with_name("loop_1-audio_topaz.mp4")
                record = sidecar.read(sidecar.sidecar_path(remade))
            assert sorted(path.name for path in played.parent.iterdir()) == [remade.name]
            assert remade.read_text(encoding="utf-8") == "upscaled again"
            assert record["favorite"]
            assert sorted(path.name for path in its_sound.parent.iterdir()) == ["loop_1-audio_topaz.mp3"]


class TestGenauDeliverResultSurface(unittest.TestCase):
    def test_the_result_carries_only_what_a_reader_consults(self):
        assert {f.name for f in dataclasses.fields(genau_deliver.GenauDeliverResult)} == {"delivered", "failed"}


if __name__ == "__main__":
    unittest.main()
