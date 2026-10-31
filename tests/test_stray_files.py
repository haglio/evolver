"""The stage that clears non-video files out of the video tree."""
from __future__ import annotations

import unittest
from pathlib import Path

from tasks import stray_files
from tests.temp_helpers import override_config, workspace_temp_dir
from util import lanes
from util.media_files import partial_path


class TestMalformedExtensions(unittest.TestCase):
    def test_a_space_before_the_extension_token_becomes_a_dot(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip mp4").write_bytes(b"video")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.renamed == 1
            assert (videos / "clip.mp4").is_file()
            assert not (videos / "clip mp4").exists()

    def test_an_ordinary_video_is_left_alone(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip.mp4").write_bytes(b"video")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.renamed == 0
            assert (videos / "clip.mp4").is_file()

    def test_an_underscore_or_a_hyphen_separator_is_repaired_too(self):
        for name, repaired in (("clip_mkv", "clip.mkv"), ("clip-webm", "clip.webm")):
            with self.subTest(name=name), workspace_temp_dir() as root:
                videos = root / "videos"
                videos.mkdir()
                (videos / name).write_bytes(b"video")

                with override_config(VIDEO_LIBRARY_DIR=videos):
                    result = stray_files.run()

                assert result.renamed == 1
                assert (videos / repaired).is_file()

    def test_a_taken_repaired_name_is_reported_rather_than_overwritten(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip mp4").write_bytes(b"malformed")
            (videos / "clip.mp4").write_bytes(b"already here")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.renamed == 0
            assert result.reported == ["clip mp4"]
            assert (videos / "clip mp4").read_bytes() == b"malformed"
            assert (videos / "clip.mp4").read_bytes() == b"already here"


class TestStrayFunscripts(unittest.TestCase):
    def test_a_funscript_in_the_video_tree_moves_to_its_mirror_path(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            scripts = root / "scripts"
            bucket = videos / "2D" / "non_AI" / "example"
            bucket.mkdir(parents=True)
            (bucket / "scene one.funscript").write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
                result = stray_files.run()

            assert result.rehomed_scripts == 1
            assert result.reported == []
            assert not (bucket / "scene one.funscript").exists()
            assert (scripts / "2D" / "non_AI" / "example" / "scene one.funscript").is_file()

    def test_a_malformed_script_name_is_repaired_and_then_rehomed(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            scripts = root / "scripts"
            videos.mkdir()
            (videos / "scene one_funscript").write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
                result = stray_files.run()

            assert result.renamed == 1
            assert result.rehomed_scripts == 1
            assert result.reported == []
            assert (scripts / "scene one.funscript").is_file()

    def test_a_taken_mirror_path_is_reported_rather_than_overwritten(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            scripts = root / "scripts"
            videos.mkdir()
            scripts.mkdir()
            (videos / "scene one.funscript").write_text("stray", encoding="utf-8")
            (scripts / "scene one.funscript").write_text("already here", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
                result = stray_files.run()

            assert result.rehomed_scripts == 0
            assert result.reported == ["scene one.funscript"]
            assert (videos / "scene one.funscript").read_text(encoding="utf-8") == "stray"
            assert (scripts / "scene one.funscript").read_text(encoding="utf-8") == "already here"


class TestScriptsOrigeneratorHandsOver(unittest.TestCase):
    def _library(self, root):
        videos = root / "videos"
        return videos, dict(VIDEO_LIBRARY_DIR=videos, INBOX_DIR=videos / "2D" / "AI" / "0_inbox",
                            SCRIPT_LIBRARY_DIR=root / "scripts",
                            GENERATED_SCRIPTS_DIR=root / "generated")

    def test_a_script_handed_over_with_its_clip_is_marked_as_no_persons(self):
        with workspace_temp_dir() as root:
            videos, folders = self._library(root)
            lane = Path("2D") / "AI" / "0_inbox" / lanes.ORIGENERATOR_SOURCE
            (videos / lane).mkdir(parents=True)
            (videos / lane / "made_00001.funscript").write_text("{}", encoding="utf-8")

            with override_config(**folders):
                stray_files.run()

            assert (root / "scripts" / lane / "made_00001.funscript").is_file()
            assert (root / "generated" / lane / "made_00001.generated").is_file()

    def test_a_script_found_anywhere_else_carries_no_mark(self):
        with workspace_temp_dir() as root:
            videos, folders = self._library(root)
            bucket = Path("2D") / "non_AI" / "example"
            (videos / bucket).mkdir(parents=True)
            (videos / bucket / "scene one.funscript").write_text("{}", encoding="utf-8")

            with override_config(**folders):
                stray_files.run()

            assert (root / "scripts" / bucket / "scene one.funscript").is_file()
            assert not (root / "generated").exists()


class TestEverythingElse(unittest.TestCase):
    def test_a_foreign_file_is_reported_and_left_where_it_is(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            bucket = videos / "2D" / "non_AI" / "example"
            bucket.mkdir(parents=True)
            (bucket / "cover.jpg").write_bytes(b"image")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.reported == [str(Path("2D") / "non_AI" / "example" / "cover.jpg")]
            assert (bucket / "cover.jpg").is_file()

    def test_the_files_windows_writes_by_itself_are_not_reported(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
            (videos / "Thumbs.db").write_bytes(b"thumbs")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.reported == []
            assert (videos / "desktop.ini").is_file()

    def test_a_partial_upscale_output_is_left_alone(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            partial = partial_path(videos / "clip_topaz.mp4", "clip")
            partial.write_bytes(b"in flight")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            assert result.reported == []
            assert partial.is_file()


if __name__ == "__main__":
    unittest.main()
