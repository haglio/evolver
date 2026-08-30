"""Where the non-AI stages think a bucket is."""

import unittest
from pathlib import Path

from tests.temp_helpers import override_config, workspace_temp_dir
from util.nonai_library import bucket_of, buckets, stage_dirs


def make_video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def library(root):
    return dict(
        VIDEO_LIBRARY_DIR=root / "videos",
        NON_AI_DIR=root / "videos" / "2D" / "non_AI",
    )


class TestBuckets(unittest.TestCase):
    def test_a_top_level_folder_holding_the_stages_is_the_bucket(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "alpha" / "0 unsorted" / "one.mp4")
            make_video(non_ai / "beta" / "3_good_to_go" / "two.mp4")
            with override_config(**overrides):
                found = buckets()
            self.assertEqual([path.name for path in found], ["alpha", "beta"])

    def test_a_folder_split_into_sub_libraries_yields_each_of_them(self):
        """The stages moved a level down, so the buckets follow them.

        A bucket is whatever holds the numbered stage folders — that is the only
        thing every stage does with one (retire into its ``2*``, publish into its
        ``3*``, scan its ``0*``/``1*`` for work).  Split a folder into two
        sub-libraries that each keep their own copy of the stages and the parent
        stops being a bucket: it has no stages of its own, and reading it as one
        leaves every stage looking for folders that are no longer there.
        """
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "alpha" / "cuts" / "0 unsorted" / "one.mp4")
            make_video(non_ai / "alpha" / "whole" / "3_good_to_go" / "two.mp4")
            with override_config(**overrides):
                found = buckets()
            self.assertEqual(
                [str(path.relative_to(non_ai)) for path in found],
                [str(Path("alpha") / "cuts"), str(Path("alpha") / "whole")],
            )

    def test_an_excluded_top_level_folder_is_skipped_however_it_is_shaped(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "alpha" / "0 unsorted" / "one.mp4")
            make_video(non_ai / "skipped" / "cuts" / "0 unsorted" / "two.mp4")
            with override_config(NONAI_EXCLUDED_BUCKETS={"skipped"}, **overrides):
                found = buckets()
            self.assertEqual([path.name for path in found], ["alpha"])


class TestBucketOf(unittest.TestCase):
    def test_finds_the_bucket_a_video_sits_under(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            video = make_video(non_ai / "alpha" / "0 unsorted" / "one.mp4")
            with override_config(**overrides):
                self.assertEqual(bucket_of(video), non_ai / "alpha")

    def test_finds_the_sub_library_when_the_folder_was_split(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            video = make_video(
                non_ai / "alpha" / "cuts" / "1 could use work" / "trimmed" / "one.mp4"
            )
            make_video(non_ai / "alpha" / "whole" / "3_good_to_go" / "two.mp4")
            with override_config(**overrides):
                self.assertEqual(bucket_of(video), non_ai / "alpha" / "cuts")

    def test_a_video_outside_the_library_has_no_bucket(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            video = make_video(root / "elsewhere" / "one.mp4")
            with override_config(**overrides):
                self.assertIsNone(bucket_of(video))


class TestSplitInProgress(unittest.TestCase):
    """A move over hundreds of files can leave a stage folder standing."""

    def test_a_leftover_stage_folder_does_not_unsplit_the_library(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "alpha" / "cuts" / "0 unsorted" / "one.mp4")
            make_video(non_ai / "alpha" / "whole" / "3_good_to_go" / "two.mp4")
            stranded = make_video(non_ai / "alpha" / "0 unsorted" / "stuck.mp4")
            with override_config(**overrides):
                found = buckets()
                self.assertEqual(
                    [str(path.relative_to(non_ai)) for path in found],
                    sorted([str(Path("alpha") / "cuts"), str(Path("alpha") / "whole")]),
                )
                self.assertIsNone(bucket_of(stranded))

    def test_a_stage_folders_own_sub_stages_are_never_read_as_libraries(self):
        with workspace_temp_dir() as root:
            overrides = library(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(
                non_ai / "alpha" / "1 could use work" / "2_needs_upscaling" / "one.mp4"
            )
            with override_config(**overrides):
                found = buckets()
            self.assertEqual([str(path.relative_to(non_ai)) for path in found], ["alpha"])


if __name__ == "__main__":
    unittest.main()


class TestStageDirs(unittest.TestCase):
    """The numbered-folder convention, read at either level of it."""

    def test_finds_only_the_digits_asked_for_and_names_each_one(self):
        with workspace_temp_dir() as root:
            for name in ("0 unsorted", "1 could use work", "2 do not need work",
                         "3_good_to_go"):
                (root / name).mkdir()

            found = stage_dirs(root, digits=(0, 1))

            self.assertEqual(
                found,
                [(0, root / "0 unsorted"), (1, root / "1 could use work")],
            )

    def test_a_triage_folders_own_sub_stages_read_the_same_way(self):
        with workspace_temp_dir() as root:
            triage = root / "1 could use work"
            (triage / "1_originals_needing_trimming").mkdir(parents=True)
            (triage / "2_originals_good_trimwise_but_need_upscaling").mkdir()

            found = stage_dirs(triage, digits=(2, 3))

            self.assertEqual(
                [path.name for _, path in found],
                ["2_originals_good_trimwise_but_need_upscaling"],
            )

    def test_files_and_unnumbered_folders_are_not_stages(self):
        with workspace_temp_dir() as root:
            (root / "processed").mkdir()
            (root / "0 notes.txt").write_text("x", encoding="utf-8")

            self.assertEqual(stage_dirs(root, digits=(0, 1, 2, 3)), [])
