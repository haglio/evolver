from __future__ import annotations

import inspect
import logging
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support.testing import no_wait_for_a_held_file

import config
from tests.temp_helpers import a_drive_that_is_not_there, override_config, workspace_temp_dir
from util import media_files
from util.media_files import (
    child_dirs,
    is_partial_path,
    library_videos,
    listed_videos,
    partial_path,
    partial_stem,
    reachable,
    remove_empty_dirs,
    remove_partial_files,
    retry_while_in_use,
    strip_uniquifier,
    take_its_place,
    unique_path,
)

_IN_USE = PermissionError(32, "The process cannot access the file")


class TestLibraryVideos(unittest.TestCase):
    def test_finds_finished_videos_at_any_depth_and_skips_partials(self):
        with workspace_temp_dir() as root:
            good = root / "a" / "clip.mp4"
            good.parent.mkdir(parents=True)
            good.write_bytes(b"video")
            partial = root / "a" / "clip.partial.deadbeef.mp4"
            partial.write_bytes(b"partial")

            with override_config(VIDEO_EXTENSIONS={".mp4"}):
                found = list(library_videos(root))

        assert found == [good]
        assert is_partial_path(partial)

    def test_video_extensions_are_read_from_config_at_each_call(self):
        with workspace_temp_dir() as root:
            mp4 = root / "clip.mp4"
            mkv = root / "clip.mkv"
            mp4.write_bytes(b"video")
            mkv.write_bytes(b"video")

            with override_config(VIDEO_EXTENSIONS={".mkv"}):
                assert list(library_videos(root)) == [mkv]

    def test_a_root_that_is_not_there_yields_nothing(self):
        with workspace_temp_dir() as root, override_config(VIDEO_EXTENSIONS={".mp4"}):
            assert list(library_videos(root / "nope")) == []


class TestListedVideos(unittest.TestCase):
    def test_finds_finished_videos_at_any_depth_without_asking_the_disk_about_any_one(self):
        with workspace_temp_dir() as root:
            good = root / "a" / "clip.mp4"
            good.parent.mkdir(parents=True)
            good.write_bytes(b"video")
            (root / "a" / "clip.partial.deadbeef.mp4").write_bytes(b"partial")
            (root / "a" / "notes.txt").write_text("notes", encoding="utf-8")

            with override_config(VIDEO_EXTENSIONS={".mp4"}), \
                    patch("os.stat", side_effect=AssertionError("asked the disk about one file")):
                found = list(listed_videos(root))

        assert found == [good]

    def test_a_root_that_is_not_there_yields_nothing(self):
        with workspace_temp_dir() as root, override_config(VIDEO_EXTENSIONS={".mp4"}):
            assert list(listed_videos(root / "nope")) == []


class TestReachable(unittest.TestCase):
    def test_an_empty_folder_can_be_reached(self):
        with workspace_temp_dir() as root:
            assert reachable(root)

    def test_a_folder_not_made_yet_on_a_drive_that_is_there_can_be_reached(self):
        with workspace_temp_dir() as root:
            assert reachable(root / "archive")

    def test_a_folder_on_a_drive_that_is_not_there_cannot_be_reached(self):
        assert not reachable(a_drive_that_is_not_there() / "cloud" / "VR")


class TestPartialPath(unittest.TestCase):
    def test_a_partial_is_named_so_nothing_that_lists_videos_takes_it_for_one(self):
        final = Path("processed") / "scene one_apo8_iris2.mp4"

        partial = partial_path(final, "scene one")

        assert partial.parent == final.parent
        assert partial.name.startswith("scene one")
        assert is_partial_path(partial)
        assert partial.suffix.lower() not in config.VIDEO_EXTENSIONS

    def test_a_retry_never_writes_over_a_partial_a_dead_encode_still_holds_open(self):
        final = Path("processed") / "scene one_apo8_iris2.mp4"

        assert partial_path(final, "scene one") != partial_path(final, "scene one")

    def test_the_stem_a_partial_was_named_for_reads_back_off_it(self):
        final = Path("processed") / "scene one_apo8_iris2.mp4"

        assert partial_stem(partial_path(final, "scene one")) == "scene one"


class TestChildDirs(unittest.TestCase):
    def test_yields_the_immediate_subdirectories_in_name_order(self):
        with workspace_temp_dir() as root:
            for name in ("zebra", "alpha", "middle"):
                (root / name).mkdir()
            (root / "alpha" / "deeper").mkdir()
            (root / "a file.txt").write_text("x", encoding="utf-8")

            assert [d.name for d in child_dirs(root)] == ["alpha", "middle", "zebra"]

    def test_a_root_that_is_not_there_yields_nothing(self):
        with workspace_temp_dir() as root:
            assert list(child_dirs(root / "nope")) == []


class TestTheUniquifier(unittest.TestCase):
    def test_a_free_name_is_left_alone(self):
        with workspace_temp_dir() as root:
            assert unique_path(root / "clip.mp4") == root / "clip.mp4"

    def test_a_file_put_there_by_hand_is_never_overwritten(self):
        with workspace_temp_dir() as root:
            (root / "clip.mp4").write_bytes(b"one")
            (root / "clip (2).mp4").write_bytes(b"two")

            assert unique_path(root / "clip.mp4") == root / "clip (3).mp4"

    def test_the_suffix_survives_and_the_number_goes_before_it(self):
        with workspace_temp_dir() as root:
            (root / "clip one.mkv").write_bytes(b"one")

            assert unique_path(root / "clip one.mkv") == root / "clip one (2).mkv"

    def test_stripping_is_the_inverse_of_appending(self):
        with workspace_temp_dir() as root:
            (root / "clip.mp4").write_bytes(b"one")

            taken = unique_path(root / "clip.mp4")

            assert strip_uniquifier(taken.stem) == "clip"

    def test_a_stem_with_no_number_comes_back_whole(self):
        assert strip_uniquifier("clip one") == "clip one"

    def test_only_a_trailing_number_in_parentheses_is_stripped(self):
        assert strip_uniquifier("clip (director's cut)") == "clip (director's cut)"
        assert strip_uniquifier("clip (2) more") == "clip (2) more"


class TestRemoveEmptyDirs(unittest.TestCase):
    def test_removes_only_empty(self):
        with workspace_temp_dir() as root:
            empty_sub = root / "a" / "b"
            nonempty_sub = root / "c"
            empty_sub.mkdir(parents=True)
            nonempty_sub.mkdir(parents=True)
            (nonempty_sub / "file.txt").write_text("x", encoding="utf-8")

            remove_empty_dirs(root)

            assert not (root / "a").exists()
            assert nonempty_sub.exists()


class TestRemovePartialFiles(unittest.TestCase):
    def test_the_logger_has_no_default(self):
        assert inspect.signature(remove_partial_files).parameters["logger"].default is inspect.Parameter.empty

    def test_takes_the_partials_and_leaves_the_rest(self):
        with workspace_temp_dir() as root:
            partial = partial_path(root / "clip_topaz.mp4", "clip")
            finished = root / "clip.mp4"
            partial.write_bytes(b"partial")
            finished.write_bytes(b"video")

            removed = remove_partial_files(root, logging.getLogger(__name__))

            assert removed == 1
            assert not partial.exists()
            assert finished.exists()

    def test_a_partial_that_will_not_delete_is_reported_and_not_counted(self):
        with workspace_temp_dir() as root:
            partial_path(root / "clip_topaz.mp4", "clip").write_bytes(b"partial")
            log = logging.getLogger(__name__)

            with patch.object(Path, "unlink", side_effect=OSError("held open")), \
                 self.assertLogs(log, level="ERROR"):
                removed = remove_partial_files(root, log)

            assert removed == 0


_THE_OLD_FILES_DATE = 1_000_000


def _replaced_over_a_file_of_the_old_date(root: Path) -> Path:
    old, new = root / "clip.mp4", root / "clip_new.mp4"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    os.utime(old, (_THE_OLD_FILES_DATE, _THE_OLD_FILES_DATE))
    take_its_place(new, old)
    assert not new.exists()
    return old


class TestTakeItsPlace(unittest.TestCase):
    def test_a_replacement_keeps_its_place_by_date(self):
        with workspace_temp_dir() as root:
            dated = _replaced_over_a_file_of_the_old_date(root).stat().st_mtime

        assert _THE_OLD_FILES_DATE < dated <= _THE_OLD_FILES_DATE + 1

    def test_a_replacement_reads_as_a_changed_file(self):
        with workspace_temp_dir() as root:
            replaced = _replaced_over_a_file_of_the_old_date(root)

            assert replaced.read_bytes() == b"new"
            assert replaced.stat().st_mtime != _THE_OLD_FILES_DATE

    def test_with_nothing_to_replace_it_keeps_its_own_date(self):
        with workspace_temp_dir() as root:
            old, new = root / "clip.mp4", root / "clip_new.mp4"
            new.write_bytes(b"new")
            os.utime(new, (2_000_000, 2_000_000))

            take_its_place(new, old)

            assert old.read_bytes() == b"new"
            assert old.stat().st_mtime == 2_000_000


class TestRetryWhileInUse(unittest.TestCase):
    def test_waits_out_a_player_that_still_holds_the_file_open(self):
        tries = []

        def held_open_once():
            tries.append(None)
            if len(tries) == 1:
                raise _IN_USE
            return "moved"

        with no_wait_for_a_held_file() as sleep:
            assert retry_while_in_use(held_open_once) == "moved"

        assert len(tries) == 2
        sleep.assert_called_once()

    def test_the_player_gets_ten_short_chances_to_let_go(self):
        tries = []

        def held_open_until_the_last_chance():
            tries.append(None)
            if len(tries) < 10:
                raise _IN_USE

        with no_wait_for_a_held_file() as sleep:
            retry_while_in_use(held_open_until_the_last_chance)

        assert len(tries) == 10
        assert [call.args[0] for call in sleep.call_args_list] == [0.2] * 9

    def test_gives_up_on_a_file_that_is_never_let_go(self):
        def always_held_open():
            raise _IN_USE

        with no_wait_for_a_held_file(), pytest.raises(PermissionError):
            retry_while_in_use(always_held_open)


class TestAFileThatCannotBeRead:
    def test_its_size_reads_as_zero(self, tmp_path):
        assert media_files.file_size(tmp_path / "gone.mp4") == 0

    def test_a_file_reads_as_its_size_in_bytes(self, tmp_path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"12345")

        assert media_files.file_size(video) == 5


if __name__ == "__main__":
    unittest.main()
