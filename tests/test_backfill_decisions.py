from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backfill.decisions import (
    discard_as_weird,
    reclaim_from_weird,
    restore_sidecar,
    sidecar_snapshot,
)
from tests.temp_helpers import library_tree, override_config, workspace_temp_dir
from util.sidecar import record_action, sidecar_path


class TestSidecarSnapshotAndRestore(unittest.TestCase):
    def test_a_clip_with_no_sidecar_snapshots_as_nothing(self):
        with library_tree() as lib:
            assert sidecar_snapshot(lib.video()) is None

    def test_restoring_nothing_deletes_the_sidecar_that_was_written(self):
        with library_tree() as lib:
            video = lib.video()

            snapshot = sidecar_snapshot(video)
            record_action(video, "Dancing")
            assert sidecar_path(video).is_file()

            restore_sidecar(video, snapshot)

            assert not sidecar_path(video).exists()

    def test_restoring_a_snapshot_puts_the_earlier_metadata_back(self):
        with library_tree() as lib:
            video = lib.video()
            earlier = {"video": {"prompt": "a prompt"}}
            path = sidecar_path(video)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(earlier), encoding="utf-8")

            snapshot = sidecar_snapshot(video)
            record_action(video, "Dancing")
            restore_sidecar(video, snapshot)

            assert json.loads(path.read_text(encoding="utf-8")) == earlier

    def test_restoring_nothing_tolerates_a_sidecar_that_was_never_written(self):
        with library_tree() as lib:
            video = lib.video()

            restore_sidecar(video, None)  # must not raise

            # ...and must not have conjured a sidecar out of the nothing
            assert not sidecar_path(video).exists()


class TestReclaimFromWeird(unittest.TestCase):
    def test_a_discarded_clip_goes_back_where_it_came_from(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            video = root / "upscaled" / "portrait" / "provider2" / "a_topaz.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"video")

            with override_config(WEIRD_DIR=weird_dir):
                destination = discard_as_weird(video)
                reclaim_from_weird(destination, video)

            assert video.is_file()
            assert video.read_bytes() == b"video"
            assert not destination.exists()


class TestDiscardAsWeird(unittest.TestCase):
    def _make_video(self, root, name="a_topaz.mp4"):
        video = root / "upscaled" / "portrait" / "provider2" / name
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def test_moves_the_video_into_the_weird_folder(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            video = self._make_video(root)

            with override_config(WEIRD_DIR=weird_dir):
                destination = discard_as_weird(video)

            assert destination == weird_dir / "a_topaz.mp4"
            assert destination.is_file()
            assert not video.exists()

    def test_a_name_collision_never_overwrites_an_earlier_discard(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            weird_dir.mkdir()
            (weird_dir / "a_topaz.mp4").write_bytes(b"earlier")
            video = self._make_video(root)

            with override_config(WEIRD_DIR=weird_dir):
                destination = discard_as_weird(video)

            assert destination.name == "a_topaz__dup1.mp4"
            assert (weird_dir / "a_topaz.mp4").read_bytes() == b"earlier"
            assert destination.read_bytes() == b"video"

    def test_waits_out_a_player_that_still_holds_the_clip_open(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            video = self._make_video(root)
            real_replace = type(video).replace
            attempts = []

            def replace_locked_once(self, target):
                attempts.append(target)
                if len(attempts) == 1:
                    raise PermissionError(32, "The process cannot access the file")
                return real_replace(self, target)

            with override_config(WEIRD_DIR=weird_dir):
                with patch.object(type(video), "replace", replace_locked_once), \
                     patch("app_support.file_channel.time.sleep") as sleep:
                    destination = discard_as_weird(video)

            assert len(attempts) == 2
            sleep.assert_called_once()
            assert destination.is_file()


if __name__ == "__main__":
    unittest.main()
