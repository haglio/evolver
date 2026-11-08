from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from util import lanes, retired_outbox, script_library, sidecar

GENAU_SOURCE = "example-loop-clips"


@contextmanager
def _library():
    with workspace_temp_dir() as root:
        lib = LaneLibrary(root)
        with lib.config(genau_source=GENAU_SOURCE, LIBRARY_ROOT=root):
            yield lib


def _in_the_old_outbox(lib: LaneLibrary, *parts: str):
    return touch_video(lib.ai.joinpath("2_outbox", *parts))


class TestMovingWhatTheRetiredOutboxHeld(unittest.TestCase):
    def test_a_kino_upscale_moves_to_kinos_folder_with_its_record_and_script(self):
        with _library() as lib:
            old = _in_the_old_outbox(lib, "upscaled_by_orientation", "portrait", "provider", "clip one_topaz.mp4")
            write_sidecar(sidecar.sidecar_path(old), {"favorite": True})
            touch_video(script_library.script_path_for_video(old))

            moved = retired_outbox.move_into_the_lane_folders()

            now = lanes.upscale_of("provider", "portrait", "clip one")
            assert (moved.moved, moved.failed) == (1, 0)
            assert now.is_file()
            assert sidecar.read(sidecar.sidecar_path(now)) == {"favorite": True}
            assert script_library.script_path_for_video(now).is_file()
            assert not (lib.ai / "2_outbox").exists()

    def test_a_genau_upscale_waiting_for_delivery_moves_to_where_genau_plays_it(self):
        with _library() as lib:
            _in_the_old_outbox(lib, "upscaled_by_orientation", "landscape", GENAU_SOURCE, "loop_1_topaz.mp4")

            retired_outbox.move_into_the_lane_folders()

            assert lanes.upscale_of(GENAU_SOURCE, "landscape", "loop_1").is_file()

    def test_a_video_in_the_old_trash_moves_to_kinos_trash_and_its_record_to_kinos_tree(self):
        with _library() as lib:
            trashed = _in_the_old_outbox(lib, "trash", "clip two_topaz.mp4")
            left_behind = lib.ai / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "clip two_topaz.mp4"
            write_sidecar(sidecar.sidecar_path(left_behind), {"favorite": False})

            retired_outbox.move_into_the_lane_folders()

            assert (lib.trash / trashed.name).is_file()
            assert sidecar.read(sidecar.sidecar_path(
                lanes.upscale_of("provider", "portrait", "clip two"))) == {"favorite": False}

    def test_a_name_already_taken_where_it_goes_stays_and_is_counted(self):
        with _library() as lib:
            old = _in_the_old_outbox(lib, "upscaled_by_orientation", "portrait", "provider", "clip one_topaz.mp4")
            touch_video(lanes.upscale_of("provider", "portrait", "clip one")).write_text("other", encoding="utf-8")

            with self.assertLogs("util.retired_outbox", level="ERROR"):
                moved = retired_outbox.move_into_the_lane_folders()

            assert (moved.moved, moved.failed) == (0, 1)
            assert old.is_file()

    def test_a_file_that_cannot_be_moved_is_left_for_the_next_run(self):
        with _library() as lib:
            old = _in_the_old_outbox(lib, "upscaled_by_orientation", "portrait", "provider", "clip one_topaz.mp4")
            with patch.object(retired_outbox, "retry_while_in_use", side_effect=OSError("in use")), \
                 self.assertLogs("util.retired_outbox", level="ERROR"):
                moved = retired_outbox.move_into_the_lane_folders()

            assert (moved.moved, moved.failed) == (0, 1)
            assert old.is_file()

    def test_a_partial_upscale_is_thrown_away_rather_than_moved(self):
        with _library() as lib:
            partial = _in_the_old_outbox(lib, "upscaled_by_orientation", "portrait", "provider", "clip.partial.abc")

            moved = retired_outbox.move_into_the_lane_folders()

            assert moved.moved == 0
            assert not partial.exists()

    def test_with_no_retired_outbox_there_is_nothing_to_do(self):
        with _library():
            assert retired_outbox.move_into_the_lane_folders() == retired_outbox.MovedOut()


if __name__ == "__main__":
    unittest.main()
