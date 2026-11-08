from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import check_correspondence
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

    def test_a_sorted_flicks_upscale_counts_only_where_genau_plays_it(self):
        with _library() as lib:
            _sorted(lib, GENAU_SOURCE, "landscape", "loop_1.mp4")
            _kino(lib, GENAU_SOURCE, "landscape", "loop_1_topaz.mp4")

            result = check_correspondence.run()

            assert result.orphan_sorted == [str(Path(GENAU_SOURCE) / "landscape" / "loop_1.mp4")]
            assert result.orphan_upscales == [
                str(Path("videos") / "videos" / "kino" / "2D" / "AI" / "landscape" / GENAU_SOURCE / "loop_1_topaz.mp4")]

    def test_a_flick_gone_from_genaus_folder_is_reported_by_the_record_it_left(self):
        with _library() as lib:
            flick = _flick(lib, "loop_1_topaz.mp4")
            write_sidecar(sidecar.sidecar_path(flick), {"video": {"seed": "1"}})
            flick.unlink()

            result = check_correspondence.run()

            assert not result.ok
            assert result.missing_flicks == [
                str(Path("videos") / "videos" / "genau" / "flicks" / "2D" / "AI" / "loop_1_topaz.mp4")]

    def test_a_copy_pcloud_made_of_a_flicks_record_is_no_flick_of_its_own(self):
        with _library() as lib:
            flick = _flick(lib, "loop_1_topaz.mp4")
            record = write_sidecar(sidecar.sidecar_path(flick), {"video": {"seed": "1"}})
            conflicted = sidecar.sidecar_path(flick).with_name("loop_1_topaz [conflicted].json")
            write_sidecar(conflicted, record)

            assert check_correspondence.run().missing_flicks == []

    def test_a_flick_sent_to_genaus_trash_is_not_missing(self):
        with _library() as lib:
            flick = _flick(lib, "loop_1_topaz.mp4")
            write_sidecar(sidecar.sidecar_path(flick), {"video": {"seed": "1"}})
            flick.replace(touch_video(lanes.in_trash(flick)))

            assert check_correspondence.run().ok

    def test_a_record_written_before_its_flick_was_upscaled_is_not_missing(self):
        with _library() as lib:
            _sorted(lib, GENAU_SOURCE, "landscape", "loop_1.mp4")
            write_sidecar(sidecar.sidecar_path(lanes.upscale_of(GENAU_SOURCE, "landscape", "loop_1")),
                          {"video": {"seed": "1"}})

            result = check_correspondence.run()

            assert result.missing_flicks == []


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
