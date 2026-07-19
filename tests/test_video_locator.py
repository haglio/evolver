import unittest
from pathlib import Path
from unittest.mock import patch

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


class TestRenamedInPlace(unittest.TestCase):
    def test_finds_the_renamed_file_by_its_frame_fingerprint(self):
        with workspace_temp_dir() as temp:
            folder = temp / "0 unsorted"
            renamed_to = _write_video(folder / "Clip_topaz.mp4")
            _write_video(folder / "something else.mp4")

            fingerprints = {renamed_to: (60.0, 70296), folder / "something else.mp4": (30.0, 2350)}
            with patch("util.video_locator.ffprobe.frame_fingerprint", fingerprints.get):
                found = video_locator.renamed_in_place(folder / "clip-1080p_60fps.mp4", (60.0, 70296))

            self.assertEqual(found, renamed_to)

    def test_declines_when_no_neighbour_matches(self):
        with workspace_temp_dir() as temp:
            folder = temp / "0 unsorted"
            _write_video(folder / "other.mp4")

            with patch("util.video_locator.ffprobe.frame_fingerprint", lambda _: (30.0, 2350)):
                found = video_locator.renamed_in_place(folder / "gone.mp4", (60.0, 70296))

            self.assertIsNone(found)

    def test_declines_when_two_neighbours_share_the_fingerprint(self):
        with workspace_temp_dir() as temp:
            folder = temp / "0 unsorted"
            _write_video(folder / "one.mp4")
            _write_video(folder / "two.mp4")

            with patch("util.video_locator.ffprobe.frame_fingerprint", lambda _: (60.0, 70296)):
                found = video_locator.renamed_in_place(folder / "gone.mp4", (60.0, 70296))

            self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
