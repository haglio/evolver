"""A funscript Origenerator hands over with its clip, carried to the upscale the Funestras show.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import scripts_sync, sort, stray_files
from tests.temp_helpers import (
    LaneLibrary,
    gallery_of_videos_made_again,
    touch_video,
    workspace_temp_dir,
)
from util import lanes, script_library
from util.sidecar import upscaled_video_path


def _where_fun_time_looks(video: Path, tree: str, suffix: str) -> Path:
    library, found, rest = str(video).partition("\\videos\\videos\\")
    assert found, video
    return Path(f"{library}\\videos\\scripts\\{tree}\\{rest}").with_suffix(suffix)


class TestAFunscriptHandedOverWithItsClip(unittest.TestCase):
    def test_reaches_the_upscale_where_the_players_look_marked_as_no_persons(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            lane = lib.inbox / lanes.ORIGENERATOR_SOURCE
            with lib.config(UNMATCHED_SCRIPTS_DIR=root / "unmatched",
                            NONAI_RETIRED_ROOT=None, VR_VIDEO_DIR=None):
                touch_video(lane / "made_00001.mp4")
                touch_video(lane / "made_00001.funscript")

                stray_files.run()
                with patch("tasks.sort.orientation_of", return_value="portrait"):
                    sort.run()
                upscale = touch_video(upscaled_video_path(
                    lanes.ORIGENERATOR_SOURCE, "portrait", "made_00001"))
                scripts_sync.run()

                self.assertTrue(_where_fun_time_looks(upscale, "scripts", ".funscript").is_file())
                self.assertTrue(_where_fun_time_looks(upscale, "generated", ".generated").is_file())
                self.assertTrue(script_library.is_marked_generated(
                    script_library.script_path_for_video(upscale)))

    def test_with_a_video_made_again_takes_the_old_scripts_place_beside_both_copies(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            lane = lib.inbox / lanes.ORIGENERATOR_SOURCE
            gallery = gallery_of_videos_made_again(root / "gallery.db", ["made_00001.mp4"])
            with lib.config(UNMATCHED_SCRIPTS_DIR=root / "unmatched", ORIGENERATOR_DB_PATH=gallery,
                            NONAI_RETIRED_ROOT=None, VR_VIDEO_DIR=None):
                sorted_copy = touch_video(
                    lib.sorted_dir / lanes.ORIGENERATOR_SOURCE / "portrait" / "made_00001.mp4")
                upscale = touch_video(upscaled_video_path(
                    lanes.ORIGENERATOR_SOURCE, "portrait", "made_00001"))
                for copy in (sorted_copy, upscale):
                    script = script_library.script_path_for_video(copy)
                    script.parent.mkdir(parents=True, exist_ok=True)
                    script.write_text("first", encoding="utf-8")
                (lane / "made_00001.mp4").parent.mkdir(parents=True)
                (lane / "made_00001.mp4").write_bytes(b"made again")
                (lane / "made_00001.funscript").write_text("again", encoding="utf-8")

                stray_files.run()
                with patch("tasks.sort.orientation_of", return_value="portrait"):
                    sort.run()
                synced = scripts_sync.run()

                self.assertTrue(synced.ok)
                for copy in (sorted_copy, upscale):
                    self.assertEqual(script_library.script_path_for_video(copy).read_text(
                        encoding="utf-8"), "again")


if __name__ == "__main__":
    unittest.main()
