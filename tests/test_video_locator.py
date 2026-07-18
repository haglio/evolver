import unittest
from pathlib import Path

import config
from tests.temp_helpers import override_config, workspace_temp_dir
from util import video_locator


def _write_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


class TestRelocate(unittest.TestCase):
    def test_finds_the_video_under_its_new_parent(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "2D" / "non_AI" / "other" / "clip.mp4")
            with override_config(VIDEO_SEARCH_ROOT=temp / "videos"):
                index = video_locator.build_index()

            was_at = temp / "videos" / "2D" / "other" / "clip.mp4"
            self.assertEqual(video_locator.relocate(was_at, index), moved_to)

    def test_declines_when_two_folders_hold_that_filename(self):
        with workspace_temp_dir() as temp:
            _write_video(temp / "videos" / "one" / "clip.mp4")
            _write_video(temp / "videos" / "two" / "clip.mp4")
            with override_config(VIDEO_SEARCH_ROOT=temp / "videos"):
                index = video_locator.build_index()

            self.assertIsNone(video_locator.relocate(temp / "gone" / "clip.mp4", index))

    def test_ignores_a_copy_awaiting_deletion_in_kinda_weird(self):
        with workspace_temp_dir() as temp:
            weird_dir = temp / "videos" / "2_outbox" / "kinda_weird"
            _write_video(weird_dir / "clip.mp4")
            with override_config(
                VIDEO_SEARCH_ROOT=temp / "videos",
                active_weird_dirs=lambda: [weird_dir],
            ):
                index = video_locator.build_index()

            self.assertIsNone(video_locator.relocate(temp / "gone" / "clip.mp4", index))


if __name__ == "__main__":
    unittest.main()
