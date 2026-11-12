from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import check_correspondence
from tests.gallery_fakes import a_gallery_of
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from util import lanes, sidecar

GENAU_SOURCE = "example-loop-clips"


@contextmanager
def _library():
    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config(genau_source=GENAU_SOURCE, LIBRARY_ROOT=root):
            yield lib


def _sorted(lib: LaneLibrary, source: str, orient: str, name: str) -> Path:
    return touch_video(lib.sorted_dir / source / orient / name)


def _kino(lib: LaneLibrary, source: str, orient: str, name: str) -> Path:
    return touch_video(lib.kino_upscales / orient / source / name)


def _sent_to_genau(lib: LaneLibrary, name: str, **columns) -> None:
    a_gallery_of(lib.gallery_db, [{
        "prompt_id": "made-1", "output_files": json.dumps([{"filename": name, "subfolder": "video"}]),
        "genau_exported_at": "2026-01-02 03:04:05", "genau_unsent_at": None, **columns}])


def _flick(lib: LaneLibrary, name: str) -> Path:
    return touch_video(lib.genau_flicks / "2D" / "AI" / name)


class TestTheUpscalesName:
    @pytest.mark.parametrize(
        ("sorted_file", "expected"),
        [
            (Path("clip.mp4"), "clip_topaz.mp4"),
            (Path("clip_apo8_gcg5.mp4"), "clip_apo8_gcg5_topaz.mp4"),
            (Path("a.mkv"), "a_topaz.mkv"),
        ],
    )
    def test_appends_topaz_before_extension(self, sorted_file, expected):
        assert check_correspondence.upscale_name(sorted_file) == expected


class TestCorrespondenceResult:
    def test_ok_with_nothing_unmatched(self):
        assert check_correspondence.CorrespondenceResult(sorted_count=5, upscale_count=7).ok

    def test_not_ok_on_an_upscale_without_its_sorted_video(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=1, upscale_count=1, orphan_upscales=["stray.mp4"])
        assert not result.ok

    def test_not_ok_on_duplicates(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=2, upscale_count=2, duplicates={"clip_topaz.mp4": ["a", "b"]})
        assert not result.ok

    def test_not_ok_on_a_missing_flick(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=0, upscale_count=0, missing_flicks=["loop_topaz.mp4"])
        assert not result.ok


class TestTheKinoLane:
    def test_each_sorted_video_has_its_upscale_in_kinos_folder(self):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _sorted(lib, "sourceB", "portrait", "clip-b_apo8_gcg5.mp4")
            _kino(lib, "sourceA", "landscape", "clip-a_topaz.mp4")
            _kino(lib, "sourceB", "portrait", "clip-b_apo8_gcg5_topaz.mp4")

            result = check_correspondence.run(show_popup=False)

            assert result.ok
            assert (result.sorted_count, result.upscale_count) == (2, 2)

    def test_an_upscale_missing_from_kinos_folder_is_reported_and_can_show_the_popup(self):
        with _library() as lib, patch("check_correspondence.show_error") as show_error:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _kino(lib, "sourceA", "landscape", "clip-b_topaz.mp4")
            _kino(lib, "sourceA", "landscape", "clip-b_topaz_cfr.mp4")

            result = check_correspondence.run(show_popup=True)

            assert not result.ok
            assert len(result.orphan_upscales) == 2
            assert result.orphan_sorted == [str(Path("sourceA") / "landscape" / "clip-a.mp4")]
            show_error.assert_called_once()

    def test_an_upscale_in_kinos_trash_still_counts_as_made(self):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            touch_video(lib.trash / "clip-a_topaz.mp4")

            assert check_correspondence.run().ok

    def test_two_upscales_sharing_a_name_are_reported(self):
        with _library() as lib:
            for orient in ("landscape", "portrait"):
                _sorted(lib, "sourceA", orient, "clip-a.mp4")
                _kino(lib, "sourceA", orient, "clip-a_topaz.mp4")

            result = check_correspondence.run(show_popup=False)

            assert not result.ok
            paths = result.duplicates["clip-a_topaz.mp4"]
            assert any("landscape" in p for p in paths)
            assert any("portrait" in p for p in paths)
            assert (result.orphan_upscales, result.orphan_sorted) == ([], [])

    def test_a_partial_upscale_is_not_counted(self):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _kino(lib, "sourceA", "landscape", "clip-a_topaz.mp4")
            _kino(lib, "sourceA", "landscape", "clip-a.partial.deadbeef.mp4")

            result = check_correspondence.run(show_popup=False)

            assert result.ok
            assert result.upscale_count == 1


class TestTheGenauLane:
    def test_a_flick_whose_sorted_copy_was_retired_is_no_orphan(self):
        with _library() as lib:
            _flick(lib, "loop_1_topaz.mp4")

            assert check_correspondence.run().ok

    def test_a_flick_sharing_its_name_with_a_kino_upscale_is_no_duplicate(self):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _kino(lib, "sourceA", "landscape", "clip-a_topaz.mp4")
            _flick(lib, "clip-a_topaz.mp4")

            result = check_correspondence.run()

            assert result.ok
            assert result.upscale_count == 2

    def test_a_sorted_flicks_upscale_counts_only_where_genau_plays_it(self):
        with _library() as lib:
            _sorted(lib, GENAU_SOURCE, "landscape", "loop_1.mp4")
            _kino(lib, GENAU_SOURCE, "landscape", "loop_1_topaz.mp4")

            result = check_correspondence.run()

            assert result.orphan_sorted == [str(Path(GENAU_SOURCE) / "landscape" / "loop_1.mp4")]
            assert result.orphan_upscales == [
                str(Path("videos") / "videos" / "kino" / "2D" / "AI" / "landscape" / GENAU_SOURCE / "loop_1_topaz.mp4")]

    def test_a_flick_sent_to_genau_and_gone_from_genaus_folder_is_reported_by_its_gallery_row(self):
        with _library() as lib:
            _sent_to_genau(lib, "loop_1.mp4")

            result = check_correspondence.run()

            assert not result.ok
            assert result.missing_flicks == [
                str(Path("videos") / "videos" / "genau" / "flicks" / "2D" / "AI" / "loop_1_topaz.mp4")]

    def test_a_flick_there_under_the_name_its_sound_copy_gave_it_is_not_missing(self):
        with _library() as lib:
            _sent_to_genau(lib, "loop_1-audio.mp4")
            _flick(lib, "loop_1-audio_topaz.mp4")

            assert check_correspondence.run().ok

    def test_a_flick_sent_to_genaus_trash_is_not_missing(self):
        with _library() as lib:
            _sent_to_genau(lib, "loop_1.mp4")
            flick = _flick(lib, "loop_1_topaz.mp4")
            flick.replace(touch_video(lanes.in_trash(flick)))

            assert check_correspondence.run().ok

    def test_a_flick_sent_before_it_was_upscaled_is_not_missing(self):
        with _library() as lib:
            _sorted(lib, GENAU_SOURCE, "landscape", "loop_1.mp4")
            _sent_to_genau(lib, "loop_1.mp4")

            result = check_correspondence.run()

            assert result.missing_flicks == []

    def test_a_video_unsent_from_genau_is_not_missing(self):
        with _library() as lib:
            _sent_to_genau(lib, "loop_1.mp4", genau_unsent_at="2026-01-03 04:05:06")

            assert check_correspondence.run().ok

    def test_a_video_never_sent_to_genau_is_not_missing(self):
        with _library() as lib:
            a_gallery_of(lib.gallery_db, [{"prompt_id": "made-1", "output_files": json.dumps(
                [{"filename": "loop_1.mp4"}]), "genau_exported_at": None}])

            assert check_correspondence.run().ok

    def test_a_flick_in_genaus_folder_the_gallery_never_sent_there_is_reported(self):
        with _library() as lib:
            _sent_to_genau(lib, "loop_1.mp4")
            _flick(lib, "loop_1_topaz.mp4")
            _flick(lib, "loop_2_topaz.mp4")

            result = check_correspondence.run()

            assert not result.ok
            assert result.flicks_never_sent == [
                str(Path("videos") / "videos" / "genau" / "flicks" / "2D" / "AI" / "loop_2_topaz.mp4")]

    def test_an_old_sidecar_left_by_a_flick_no_longer_says_it_is_missing(self):
        with _library() as lib:
            write_sidecar(sidecar.sidecar_path(lib.genau_flicks / "2D" / "AI" / "loop_1_topaz.mp4"),
                          {"video": {"seed": "1"}})

            assert check_correspondence.run().ok

    def test_a_gallery_that_cannot_be_read_reports_no_flick_either_way(self):
        with _library() as lib:
            _flick(lib, "loop_2_topaz.mp4")
            lib.gallery_db.write_bytes(b"not a database, made up for this test")

            result = check_correspondence.run()

            assert (result.missing_flicks, result.flicks_never_sent) == ([], [])


class TestTheExitCodeAShellOrScheduledTaskReads:
    def test_a_clean_tree_reports_ok_and_exits_zero(self, capsys):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _kino(lib, "sourceA", "landscape", "clip-a_topaz.mp4")

            exit_code = check_correspondence.main()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "[OK]" in out

    def test_a_mismatched_tree_names_the_unmatched_and_exits_one(self, capsys):
        with _library() as lib:
            _sorted(lib, "sourceA", "landscape", "clip-a.mp4")
            _kino(lib, "sourceA", "landscape", "clip-b_topaz.mp4")

            exit_code = check_correspondence.main()

        out = capsys.readouterr().out
        assert exit_code == 1
        assert "Upscales without their 1_sorted video: 1" in out
        assert "clip-b_topaz.mp4" in out
        assert "1_sorted videos without their upscale: 1" in out
        assert "[FAIL]" in out

    def test_a_missing_flick_is_named_in_the_word_genau_shows(self, capsys):
        with _library() as lib, patch("config.GENAU_FLICKS_WORD", "loopies"):
            _sent_to_genau(lib, "loop_1.mp4")
            _flick(lib, "loop_2_topaz.mp4")

            check_correspondence.main()

        out = capsys.readouterr().out
        assert "Genau loopies missing from Genau's folder: 1" in out
        assert "Genau loopies in Genau's folder that Origenerator never sent there: 1" in out
        assert "Genau flicks" not in out
