import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import scripts_sync
from tests.temp_helpers import override_config, workspace_temp_dir


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

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

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

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            self.assertEqual(result.ambiguous, 1)
            self.assertTrue(script_path.exists())

    def test_ai_script_ignores_duplicate_non_ai_video_match(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            ai_video = video_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider3" / "clip_topaz.mp4"
            non_ai_duplicate = video_root / "2D" / "non_AI" / "actually_AI_but_funscripted" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider3" / "clip_topaz.mp4"
            script_path = script_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider3" / "clip_topaz.funscript"
            ai_video.parent.mkdir(parents=True, exist_ok=True)
            non_ai_duplicate.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            ai_video.write_bytes(b"ai-video")
            non_ai_duplicate.write_bytes(b"duplicate")
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            self.assertEqual(result.ambiguous, 0)
            self.assertEqual(result.already_aligned, 1)
            self.assertTrue(script_path.exists())

    def test_non_ai_script_ignores_ai_video_match(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            non_ai_video = video_root / "2D" / "non_AI" / "site" / "0 unsorted" / "clip.mp4"
            ai_video = video_root / "2D" / "AI" / "1_sorted" / "site" / "portrait" / "clip.mp4"
            script_path = script_root / "2D" / "non_AI" / "site" / "0 unsorted" / "clip.funscript"
            non_ai_video.parent.mkdir(parents=True, exist_ok=True)
            ai_video.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            non_ai_video.write_bytes(b"non-ai-video")
            ai_video.write_bytes(b"ai-video")
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            self.assertEqual(result.ambiguous, 0)
            self.assertEqual(result.already_aligned, 1)
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

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            self.assertEqual(result.already_aligned, 1)
            self.assertTrue(script_path.exists())

    def test_shows_popup_when_unmatched_scripts_remain(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            script_path = script_root / "unsorted" / "clip.funscript"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                with patch("tasks.scripts_sync.show_error_window") as show_error_window:
                    result = scripts_sync.run(show_popup=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.unmatched, 1)
            show_error_window.assert_called_once()

    def test_copies_ai_script_from_sorted_to_outbox_variant(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            sorted_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            sorted_script.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            outbox_script = script_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.funscript"
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

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

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

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                result = scripts_sync.run()

            original_script = script_root / "2D" / "non_AI" / "larkin" / "0 unsorted" / "clip.funscript"
            self.assertEqual(result.copied_variants, 1)
            self.assertTrue(original_script.exists())
            self.assertEqual(original_script.read_text(encoding="utf-8"), processed_script.read_text(encoding="utf-8"))

    def test_records_which_scripts_went_unmatched(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            script_path = script_root / "unsorted" / "clip.funscript"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=None):
                result = scripts_sync.run()

            self.assertEqual(result.unmatched_paths, [str(Path("unsorted", "clip.funscript"))])

    def test_reports_variant_copy_error_without_crashing(self):
        with workspace_temp_dir() as root:
            video_root = root / "videos"
            script_root = root / "scripts"
            sorted_video = video_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.mp4"
            outbox_video = video_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4"
            sorted_script = script_root / "2D" / "AI" / "1_sorted" / "src" / "portrait" / "clip.funscript"
            sorted_video.parent.mkdir(parents=True, exist_ok=True)
            outbox_video.parent.mkdir(parents=True, exist_ok=True)
            sorted_script.parent.mkdir(parents=True, exist_ok=True)
            sorted_video.write_bytes(b"video")
            outbox_video.write_bytes(b"upscaled")
            sorted_script.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root):
                with patch("tasks.scripts_sync.shutil.copy2", side_effect=PermissionError("denied")):
                    result = scripts_sync.run()

            outbox_script = script_root / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.funscript"
            self.assertEqual(result.variant_copy_errors, 1)
            self.assertEqual(result.copied_variants, 0)
            self.assertFalse(result.ok)
            self.assertFalse(outbox_script.exists())


class TestFollowRetiredVideos(unittest.TestCase):
    """A script whose video was archived should follow it out, not fail forever.

    Retiring an original moves it out of the library, and the script tree mirrors
    only the library — so a funscript left behind matches no video on every run
    from then on, and the stage can never go green again by itself.
    """

    def _tree(self, root):
        video_root = root / "videos"
        script_root = root / "scripts"
        archive_root = root / "archive"
        for path in (video_root, script_root, archive_root):
            path.mkdir(parents=True, exist_ok=True)
        return video_root, script_root, archive_root

    def test_orphan_script_rehomes_to_surviving_upscaled_variant(self):
        """An upscaled sibling still in the library inherits the retired
        original's script — one funscript serves every variant of a video, so
        upscaling must never strand the surviving copy scriptless."""
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            variant = video_root / "2D" / "non_AI" / "studio" / "3 done" / "processed" / "scene one_apo8_iris2.mp4"
            archived = archive_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.mp4"
            orphan = script_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.funscript"
            for path in (variant, archived):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"video")
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            rehomed = script_root / "2D" / "non_AI" / "studio" / "3 done" / "processed" / "scene one_apo8_iris2.funscript"
            self.assertTrue(result.ok)
            self.assertEqual(result.rehomed_to_variants, 1)
            self.assertEqual(result.followed_to_archive, 1)
            self.assertFalse(orphan.exists())
            self.assertEqual(rehomed.read_text(encoding="utf-8"), '{"actions":[1]}')
            self.assertEqual(archived.with_suffix(".funscript").read_text(encoding="utf-8"),
                             '{"actions":[1]}')

    def test_orphan_follows_archive_when_variant_already_scripted(self):
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            variant = video_root / "2D" / "non_AI" / "studio" / "3 done" / "processed" / "scene one_apo8_iris2.mp4"
            variant_script = script_root / "2D" / "non_AI" / "studio" / "3 done" / "processed" / "scene one_apo8_iris2.funscript"
            archived = archive_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.mp4"
            orphan = script_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.funscript"
            for path in (variant, archived):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"video")
            variant_script.parent.mkdir(parents=True, exist_ok=True)
            variant_script.write_text('{"actions":[7]}', encoding="utf-8")
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            self.assertEqual(result.rehomed_to_variants, 0)
            self.assertEqual(result.followed_to_archive, 1)
            self.assertEqual(variant_script.read_text(encoding="utf-8"), '{"actions":[7]}')
            self.assertFalse(orphan.exists())

    def test_moves_script_beside_its_archived_video(self):
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            archived_video = archive_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.mp4"
            script_path = script_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.funscript"
            archived_video.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            archived_video.write_bytes(b"video")
            script_path.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            followed = archived_video.with_suffix(".funscript")
            self.assertTrue(result.ok)
            self.assertEqual(result.unmatched, 0)
            self.assertEqual(result.followed_to_archive, 1)
            self.assertFalse(script_path.exists())
            self.assertEqual(followed.read_text(encoding="utf-8"), '{"actions":[1]}')

    def test_discards_the_identical_duplicate_left_under_another_folder(self):
        """Two library folders can hold the same script for one archived video."""
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            archived_video = archive_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.mp4"
            first = script_root / "2D" / "non_AI" / "studio" / "1 to do" / "scene one.funscript"
            second = script_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.funscript"
            archived_video.parent.mkdir(parents=True, exist_ok=True)
            archived_video.write_bytes(b"video")
            for path in (first, second):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.followed_to_archive, 1)
            self.assertEqual(result.discarded_duplicates, 1)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(archived_video.with_suffix(".funscript").exists())

    def test_keeps_a_differing_duplicate_and_calls_it_a_collision(self):
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            archived_video = archive_root / "2D" / "non_AI" / "studio" / "2 retired" / "scene one.mp4"
            archived_script = archived_video.with_suffix(".funscript")
            script_path = script_root / "2D" / "non_AI" / "studio" / "1 to do" / "scene one.funscript"
            archived_video.parent.mkdir(parents=True, exist_ok=True)
            archived_video.write_bytes(b"video")
            archived_script.write_text('{"actions":[9]}', encoding="utf-8")
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text('{"actions":[1]}', encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            self.assertFalse(result.ok)
            self.assertEqual(result.collisions, 1)
            self.assertEqual(result.followed_to_archive, 0)
            self.assertTrue(script_path.exists())
            self.assertEqual(archived_script.read_text(encoding="utf-8"), '{"actions":[9]}')

    def test_leaves_the_script_when_two_archived_videos_share_its_name(self):
        """Which video it belongs to is a guess, so it stays for a person."""
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            script_path = script_root / "2D" / "non_AI" / "studio" / "scene one.funscript"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")
            for bucket in ("alpha", "beta"):
                video = archive_root / bucket / "scene one.mp4"
                video.parent.mkdir(parents=True, exist_ok=True)
                video.write_bytes(b"video")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                result = scripts_sync.run()

            self.assertEqual(result.unmatched, 1)
            self.assertEqual(result.followed_to_archive, 0)
            self.assertTrue(script_path.exists())

    def test_a_failed_move_leaves_the_script_unmatched_rather_than_crashing(self):
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            archived_video = archive_root / "scene one.mp4"
            script_path = script_root / "2D" / "non_AI" / "studio" / "scene one.funscript"
            archived_video.write_bytes(b"video")
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                with patch("tasks.scripts_sync.shutil.move", side_effect=OSError("denied")):
                    result = scripts_sync.run()

            self.assertFalse(result.ok)
            self.assertEqual(result.unmatched, 1)
            self.assertTrue(script_path.exists())

    def test_does_not_walk_the_archive_when_every_script_matched(self):
        """An ordinary run must not touch the archive drive at all."""
        with workspace_temp_dir() as root:
            video_root, script_root, archive_root = self._tree(root)
            video_path = video_root / "2D" / "AI" / "clip.mp4"
            script_path = script_root / "2D" / "AI" / "clip.funscript"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"video")
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=archive_root):
                with patch("tasks.scripts_sync._index_archived_videos") as index_archived:
                    result = scripts_sync.run()

            self.assertEqual(result.already_aligned, 1)
            index_archived.assert_not_called()

    def test_unset_archive_keeps_the_script_unmatched(self):
        with workspace_temp_dir() as root:
            video_root, script_root, _ = self._tree(root)
            script_path = script_root / "2D" / "non_AI" / "studio" / "scene one.funscript"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("{}", encoding="utf-8")

            with override_config(VIDEO_LIBRARY_DIR=video_root, SCRIPT_LIBRARY_DIR=script_root,
                                 NONAI_RETIRED_ROOT=None):
                result = scripts_sync.run()

            self.assertEqual(result.unmatched, 1)
            self.assertTrue(script_path.exists())
