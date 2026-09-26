"""A funscript Origenerator hands over with its clip, carried to the upscale the players show.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import scripts_sync, sort, stray_files
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
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


if __name__ == "__main__":
    unittest.main()
