from __future__ import annotations

import io
import json
import unittest

import delete_from_trash
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir


class _InALibrary(unittest.TestCase):
    def setUp(self):
        workspace = workspace_temp_dir()
        self.lib = LaneLibrary(workspace.__enter__())
        self.addCleanup(workspace.__exit__, None, None, None)
        configured = self.lib.config()
        configured.__enter__()
        self.addCleanup(configured.__exit__, None, None, None)

    def _delete(self, *videos) -> dict:
        said = io.StringIO()
        delete_from_trash.main([str(video) for video in videos], out=said,
                               log_to=lambda: None)
        return json.loads(said.getvalue().strip().splitlines()[-1])


class TestDeletingWhatAnotherAppSentToTrash(_InALibrary):
    def test_a_kino_video_goes_with_the_copy_it_was_upscaled_from(self):
        source = touch_video(self.lib.sorted_dir / "example-source" / "portrait" / "scene one.mp4")
        marked = touch_video(self.lib.trash / "scene one_topaz.mp4")

        said = self._delete(marked)

        assert said == {"deleted": 1}
        assert not marked.exists()
        assert not source.exists()

    def test_a_genau_video_goes_with_its_sound(self):
        marked = touch_video(self.lib.genau_trash / "2D" / "AI" / "loop_one_topaz.mp4")
        sound = touch_video(self.lib.genau_audio / "loop_one_topaz.mp3")

        said = self._delete(marked)

        assert said == {"deleted": 1}
        assert not marked.exists()
        assert not sound.exists()

    def test_a_video_outside_the_trash_folders_is_never_deleted(self):
        playing = touch_video(self.lib.kino_upscales / "portrait" / "example-source" / "scene two_topaz.mp4")

        said = self._delete(playing)

        assert said == {"deleted": 0}
        assert playing.is_file()

    def test_a_video_already_gone_is_counted_as_nothing(self):
        said = self._delete(self.lib.trash / "scene three_topaz.mp4")

        assert said == {"deleted": 0}

    def test_only_the_videos_it_was_named_go(self):
        named = touch_video(self.lib.trash / "scene four_topaz.mp4")
        other = touch_video(self.lib.trash / "scene five_topaz.mp4")

        self._delete(named)

        assert not named.exists()
        assert other.is_file()


if __name__ == "__main__":
    unittest.main()
