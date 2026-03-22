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

    def test_copies_ai_script_from_sorted_to_outbox_variant(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            sorted_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            sorted_script.write_text('{"actions":[1]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            outbox_script = script_root / "2D" / "AI" / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.funscript"
            self.assertEqual(result.copied_variants, 1)
            self.assertTrue(outbox_script.exists())
            self.assertEqual(outbox_script.read_text(encoding="utf-8"), sorted_script.read_text(encoding="utf-8"))

    def test_copies_ai_script_from_outbox_to_sorted_variant(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "landscape" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "landscape" / "src" / "clip_topaz.mp4"
            outbox_script = script_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "landscape" / "src" / "clip_topaz.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            outbox_script.write_text('{"actions":[2]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "landscape" / "clip.funscript"
            self.assertEqual(result.copied_variants, 1)
            self.assertTrue(sorted_script.exists())
            self.assertEqual(sorted_script.read_text(encoding="utf-8"), outbox_script.read_text(encoding="utf-8"))

    def test_copies_processed_script_to_unprocessed_variant_within_source_bucket(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            original_video = video_root / "2D" / "non_AI" / "larkin" / "0 unsorted" / "clip.mp4"
            processed_video = video_root / "2D" / "non_AI" / "larkin" / "3_good_to_go" / "processed" / "clip_apo8_iris2.mp4"
            processed_script = script_root / "2D" / "non_AI" / "larkin" / "3_good_to_go" / "processed" / "clip_apo8_iris2.funscript"
            original_video.parent.mkdir(parents=True, exist_ok=True)
            processed_video.parent.mkdir(parents=True, exist_ok=True)
            processed_script.parent.mkdir(parents=True, exist_ok=True)
            original_video.write_bytes(b"video")
            processed_video.write_bytes(b"processed")
            processed_script.write_text('{"actions":[3]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            original_script = script_root / "2D" / "non_AI" / "larkin" / "0 unsorted" / "clip.funscript"
            self.assertEqual(result.copied_variants, 1)
            self.assertTrue(original_script.exists())
            self.assertEqual(original_script.read_text(encoding="utf-8"), processed_script.read_text(encoding="utf-8"))

    def test_reports_variant_copy_error_without_crashing(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            sorted_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            sorted_script.write_text('{"actions":[1]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                with patch("tasks.scripts_sync.shutil.copy2", side_effect=PermissionError("denied")):
                    result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            outbox_script = script_root / "2D" / "AI" / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.funscript"
            self.assertEqual(result.variant_copy_errors, 1)
            self.assertEqual(result.copied_variants, 0)
            self.assertFalse(result.ok)
            self.assertFalse(outbox_script.exists())

    def test_duplicates_ai_video_into_primary_vlc_folder_when_script_exists(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            duplicate_root = video_root / "2D" / "non_AI" / "actually_AI_but_funscripted"
            video_path = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            script_path = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"video")
            script_path.write_text('{"actions":[4]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            duplicate_path = duplicate_root / "1_sorted" / "src" / "portrait" / "clip.mp4"
            self.assertEqual(result.duplicated_ai_videos, 1)
            self.assertEqual(result.ai_video_duplicate_errors, 0)
            self.assertTrue(duplicate_path.exists())
            self.assertEqual(duplicate_path.read_bytes(), video_path.read_bytes())

    def test_duplicates_outbox_ai_video_after_variant_script_is_created(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            duplicate_root = video_root / "2D" / "non_AI" / "actually_AI_but_funscripted"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            sorted_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            sorted_script.write_text('{"actions":[5]}', encoding="utf-8")

            saved_video_root = config.VIDEO_LIBRARY_DIR
            saved_script_root = config.SCRIPT_LIBRARY_DIR
            config.VIDEO_LIBRARY_DIR = video_root
            config.SCRIPT_LIBRARY_DIR = script_root
            try:
                result = scripts_sync.run()
            finally:
                config.VIDEO_LIBRARY_DIR = saved_video_root
                config.SCRIPT_LIBRARY_DIR = saved_script_root

            sorted_duplicate = duplicate_root / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_duplicate = duplicate_root / "3_new_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            self.assertEqual(result.copied_variants, 1)
            self.assertEqual(result.duplicated_ai_videos, 2)
            self.assertTrue(sorted_duplicate.exists())
            self.assertTrue(outbox_duplicate.exists())
            self.assertEqual(outbox_duplicate.read_bytes(), outbox_video.read_bytes())
