"""The stage that clears non-video files out of the video tree."""

import unittest
from pathlib import Path

from tasks import stray_files
from tests.temp_helpers import override_config, workspace_temp_dir


class TestMalformedExtensions(unittest.TestCase):
    def test_a_space_before_the_extension_token_becomes_a_dot(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip mp4").write_bytes(b"video")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(result.renamed, 1)
            self.assertTrue((videos / "clip.mp4").is_file())
            self.assertFalse((videos / "clip mp4").exists())

    def test_an_ordinary_video_is_left_alone(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip.mp4").write_bytes(b"video")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(result.renamed, 0)
            self.assertTrue((videos / "clip.mp4").is_file())

    def test_an_underscore_or_a_hyphen_separator_is_repaired_too(self):
        for name, repaired in (("clip_mkv", "clip.mkv"), ("clip-webm", "clip.webm")):
            with self.subTest(name=name):
                with workspace_temp_dir() as root:
                    videos = root / "videos"
                    videos.mkdir()
                    (videos / name).write_bytes(b"video")

                    with override_config(VIDEO_LIBRARY_DIR=videos):
                        result = stray_files.run()

                    self.assertEqual(result.renamed, 1)
                    self.assertTrue((videos / repaired).is_file())

    def test_a_taken_repaired_name_is_reported_rather_than_overwritten(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "clip mp4").write_bytes(b"malformed")
            (videos / "clip.mp4").write_bytes(b"already here")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(result.renamed, 0)
            self.assertEqual(result.reported, ["clip mp4"])
            self.assertEqual((videos / "clip mp4").read_bytes(), b"malformed")
            self.assertEqual((videos / "clip.mp4").read_bytes(), b"already here")


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

            self.assertEqual(result.rehomed_scripts, 1)
            self.assertEqual(result.reported, [])
            self.assertFalse((bucket / "scene one.funscript").exists())
            self.assertTrue(
                (scripts / "2D" / "non_AI" / "example" / "scene one.funscript").is_file()
            )

    def test_a_malformed_script_name_is_repaired_and_then_rehomed(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            scripts = root / "scripts"
            videos.mkdir()
            (videos / "scene one_funscript").write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=videos, SCRIPT_LIBRARY_DIR=scripts):
                result = stray_files.run()

            self.assertEqual(result.renamed, 1)
            self.assertEqual(result.rehomed_scripts, 1)
            self.assertEqual(result.reported, [])
            self.assertTrue((scripts / "scene one.funscript").is_file())

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

            self.assertEqual(result.rehomed_scripts, 0)
            self.assertEqual(result.reported, ["scene one.funscript"])
            self.assertEqual(
                (videos / "scene one.funscript").read_text(encoding="utf-8"), "stray"
            )
            self.assertEqual(
                (scripts / "scene one.funscript").read_text(encoding="utf-8"), "already here"
            )


class TestEverythingElse(unittest.TestCase):
    def test_a_foreign_file_is_reported_and_left_where_it_is(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            bucket = videos / "2D" / "non_AI" / "example"
            bucket.mkdir(parents=True)
            (bucket / "cover.jpg").write_bytes(b"image")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(
                result.reported, [str(Path("2D") / "non_AI" / "example" / "cover.jpg")]
            )
            self.assertTrue((bucket / "cover.jpg").is_file())

    def test_the_files_windows_writes_by_itself_are_not_reported(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            (videos / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
            (videos / "Thumbs.db").write_bytes(b"thumbs")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(result.reported, [])
            self.assertTrue((videos / "desktop.ini").is_file())

    def test_a_partial_upscale_output_is_left_alone(self):
        with workspace_temp_dir() as root:
            videos = root / "videos"
            videos.mkdir()
            partial = videos / "clip.partial.abc123.mp4"
            partial.write_bytes(b"in flight")

            with override_config(VIDEO_LIBRARY_DIR=videos):
                result = stray_files.run()

            self.assertEqual(result.reported, [])
            self.assertTrue(partial.is_file())


if __name__ == "__main__":
    unittest.main()
