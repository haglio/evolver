import unittest
from unittest.mock import patch

import config
from tasks import scripts_sync
from tests.temp_helpers import workspace_temp_dir


class TestScriptsSync(unittest.TestCase):
    def test_moves_script_to_parallel_video_subdirectory(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            video_path = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            old_script_path = script_root / "unsorted" / "clip.funscript"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            old_script_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"video")
            old_script_path.write_text("{}", encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            expected = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            self.assertEqual(result.moved, 1)
            self.assertTrue(expected.exists())
            self.assertFalse(old_script_path.exists())
            self.assertFalse((script_root / "unsorted").exists())

    def test_leaves_script_when_video_match_is_ambiguous(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            first = video_root / "2D" / "AI" / "1_sorted" / "src_a" / "portrait" / "clip.mp4"
            second = video_root / "VR" / "site" / "clip.mkv"
            script_path = script_root / "unsorted" / "clip.funscript"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"video-a")
            second.write_bytes(b"video-b")
            script_path.write_text("{}", encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            self.assertEqual(result.ambiguous, 1)
            self.assertTrue(script_path.exists())

    def test_counts_script_as_already_aligned(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            video_path = video_root / "2D" / "AI" / "clip.mp4"
            script_path = script_root / "2D" / "AI" / "clip.funscript"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"video")
            script_path.write_text("{}", encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            self.assertEqual(result.already_aligned, 1)
            self.assertTrue(script_path.exists())

    def test_shows_popup_when_unmatched_scripts_remain(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            script_path = script_root / "unsorted" / "clip.funscript"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                with patch("tasks.scripts_sync.show_error_window") as show_error_window:
                    result = scripts_sync.run(show_popup=True)
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            self.assertFalse(result.ok)
            self.assertEqual(result.unmatched, 1)
            show_error_window.assert_called_once()
