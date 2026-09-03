"""What counts as a video in this library, and how the tree is walked.

These moved out of tests/test_sort.py, where they had ended up because the sort
stage was the first caller: none of them is about sorting.
"""

import inspect
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.temp_helpers import override_config, workspace_temp_dir
from util.media_files import (
    child_dirs,
    is_partial_video_path,
    library_videos,
    remove_empty_dirs,
    remove_partial_video_files,
    strip_uniquifier,
    unique_path,
)


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

        self.assertEqual(found, [good])
        self.assertTrue(is_partial_video_path(partial))

    def test_what_counts_as_a_video_is_read_when_it_is_asked_not_at_import(self):
        """Five stages threaded config.VIDEO_EXTENSIONS through one-line
        wrappers to say this; it is read here now, and still at call time, so
        override_config reaches it."""
        with workspace_temp_dir() as root:
            mp4 = root / "clip.mp4"
            mkv = root / "clip.mkv"
            mp4.write_bytes(b"video")
            mkv.write_bytes(b"video")

            with override_config(VIDEO_EXTENSIONS={".mkv"}):
                self.assertEqual(list(library_videos(root)), [mkv])

    def test_a_root_that_is_not_there_yields_nothing(self):
        with workspace_temp_dir() as root:
            with override_config(VIDEO_EXTENSIONS={".mp4"}):
                self.assertEqual(list(library_videos(root / "nope")), [])


class TestChildDirs(unittest.TestCase):
    def test_yields_the_immediate_subdirectories_in_name_order(self):
        with workspace_temp_dir() as root:
            for name in ("zebra", "alpha", "middle"):
                (root / name).mkdir()
            (root / "alpha" / "deeper").mkdir()
            (root / "a file.txt").write_text("x", encoding="utf-8")

            self.assertEqual(
                [d.name for d in child_dirs(root)], ["alpha", "middle", "zebra"]
            )

    def test_a_root_that_is_not_there_yields_nothing(self):
        """The one copy of this that left the guard off raised on a root the
        pipeline had not created yet."""
        with workspace_temp_dir() as root:
            self.assertEqual(list(child_dirs(root / "nope")), [])


class TestTheUniquifier(unittest.TestCase):
    """"stem", then "stem (2)", "stem (3)"... -- a contract between two apps.

    Origenerator applies it exporting into Evolver's inbox, Evolver applies it
    again delivering into Genau's folder, and Evolver strips it back off to
    match a library file to the row that produced it. Three expressions of one
    rule; two of them are here now, side by side, and cannot drift.
    """

    def test_a_free_name_is_left_alone(self):
        with workspace_temp_dir() as root:
            self.assertEqual(unique_path(root / "clip.mp4"), root / "clip.mp4")

    def test_a_taken_name_gets_the_next_free_number(self):
        with workspace_temp_dir() as root:
            (root / "clip.mp4").write_bytes(b"one")
            (root / "clip (2).mp4").write_bytes(b"two")

            self.assertEqual(unique_path(root / "clip.mp4"), root / "clip (3).mp4")

    def test_the_suffix_survives_and_the_number_goes_before_it(self):
        with workspace_temp_dir() as root:
            (root / "clip one.mkv").write_bytes(b"one")

            self.assertEqual(
                unique_path(root / "clip one.mkv"), root / "clip one (2).mkv"
            )

    def test_stripping_is_the_inverse_of_appending(self):
        with workspace_temp_dir() as root:
            (root / "clip.mp4").write_bytes(b"one")

            taken = unique_path(root / "clip.mp4")

            self.assertEqual(strip_uniquifier(taken.stem), "clip")

    def test_a_stem_with_no_number_comes_back_whole(self):
        self.assertEqual(strip_uniquifier("clip one"), "clip one")

    def test_only_a_trailing_number_in_parentheses_is_stripped(self):
        """A title is free to hold parentheses of its own."""
        self.assertEqual(strip_uniquifier("clip (director's cut)"), "clip (director's cut)")
        self.assertEqual(strip_uniquifier("clip (2) more"), "clip (2) more")


class TestRemoveEmptyDirs(unittest.TestCase):
    def test_removes_only_empty(self):
        with workspace_temp_dir() as root:
            empty_sub = root / "a" / "b"
            nonempty_sub = root / "c"
            empty_sub.mkdir(parents=True)
            nonempty_sub.mkdir(parents=True)
            (nonempty_sub / "file.txt").write_text("x", encoding="utf-8")

            remove_empty_dirs(root)

            self.assertFalse((root / "a").exists())
            self.assertTrue(nonempty_sub.exists())


class TestRemovePartialVideoFiles(unittest.TestCase):
    def test_takes_the_partials_and_leaves_the_rest(self):
        """Its one caller always hands it a logger, so it does not carry a
        branch for the case where it has none."""
        self.assertIs(
            inspect.signature(remove_partial_video_files).parameters["logger"].default,
            inspect.Parameter.empty,
        )
        with workspace_temp_dir() as root:
            partial = root / "clip.partial.deadbeef.mp4"
            finished = root / "clip.mp4"
            partial.write_bytes(b"partial")
            finished.write_bytes(b"video")

            removed = remove_partial_video_files(root, {".mp4"}, logging.getLogger(__name__))

            self.assertEqual(removed, 1)
            self.assertFalse(partial.exists())
            self.assertTrue(finished.exists())

    def test_a_partial_that_will_not_delete_is_reported_and_not_counted(self):
        with workspace_temp_dir() as root:
            (root / "clip.partial.deadbeef.mp4").write_bytes(b"partial")
            log = logging.getLogger(__name__)

            with patch.object(Path, "unlink", side_effect=OSError("held open")), \
                 self.assertLogs(log, level="ERROR"):
                removed = remove_partial_video_files(root, {".mp4"}, log)

            self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
