import json
import unittest
from unittest.mock import patch

from backfill.decisions import (
    discard_as_weird,
    reclaim_from_weird,
    record_action,
    restore_sidecar,
    sidecar_snapshot,
)
from tests.temp_helpers import override_config, workspace_temp_dir
from util.sidecar import sidecar_path


class TestRecordAction(unittest.TestCase):
    def _tree(self, root):
        ai = root / "AI"
        return ai, ai / "2_outbox" / "upscaled_by_orientation", root / "metadata"

    def _make_video(self, upscaled):
        video = upscaled / "portrait" / "provider2" / "a_topaz.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def test_writes_a_sidecar_recording_the_action(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                record_action(video, "Side Gamma")
                payload = json.loads(sidecar_path(video).read_text(encoding="utf-8"))

            self.assertEqual(payload, {"video": {"action": "Side Gamma"}})

    def test_keeps_the_metadata_an_existing_sidecar_already_holds(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                path = sidecar_path(video)
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps({"video": {"prompt": "a prompt"}, "source_image": {"seed": "7"}}),
                    encoding="utf-8",
                )

                record_action(video, "Dancing")
                payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(
                payload,
                {"video": {"prompt": "a prompt", "action": "Dancing"}, "source_image": {"seed": "7"}},
            )

    def test_relabelling_replaces_the_previous_action(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                record_action(video, "Dancing")
                record_action(video, "POV Epsilon")
                payload = json.loads(sidecar_path(video).read_text(encoding="utf-8"))

            self.assertEqual(payload, {"video": {"action": "POV Epsilon"}})


class TestSidecarSnapshotAndRestore(unittest.TestCase):
    def _tree(self, root):
        ai = root / "AI"
        return ai, ai / "2_outbox" / "upscaled_by_orientation", root / "metadata"

    def _make_video(self, upscaled):
        video = upscaled / "portrait" / "provider2" / "a_topaz.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def test_a_clip_with_no_sidecar_snapshots_as_nothing(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertIsNone(sidecar_snapshot(video))

    def test_restoring_nothing_deletes_the_sidecar_that_was_written(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                snapshot = sidecar_snapshot(video)
                record_action(video, "Dancing")
                self.assertTrue(sidecar_path(video).is_file())

                restore_sidecar(video, snapshot)

                self.assertFalse(sidecar_path(video).exists())

    def test_restoring_a_snapshot_puts_the_earlier_metadata_back(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)
            earlier = {"video": {"prompt": "a prompt"}}

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                path = sidecar_path(video)
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(earlier), encoding="utf-8")

                snapshot = sidecar_snapshot(video)
                record_action(video, "Dancing")
                restore_sidecar(video, snapshot)

                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), earlier)

    def test_restoring_nothing_tolerates_a_sidecar_that_was_never_written(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                restore_sidecar(video, None)  # must not raise


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

            self.assertTrue(video.is_file())
            self.assertEqual(video.read_bytes(), b"video")
            self.assertFalse(destination.exists())


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

            self.assertEqual(destination, weird_dir / "a_topaz.mp4")
            self.assertTrue(destination.is_file())
            self.assertFalse(video.exists())

    def test_a_name_collision_never_overwrites_an_earlier_discard(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            weird_dir.mkdir()
            (weird_dir / "a_topaz.mp4").write_bytes(b"earlier")
            video = self._make_video(root)

            with override_config(WEIRD_DIR=weird_dir):
                destination = discard_as_weird(video)

            self.assertEqual(destination.name, "a_topaz__dup1.mp4")
            self.assertEqual((weird_dir / "a_topaz.mp4").read_bytes(), b"earlier")
            self.assertEqual(destination.read_bytes(), b"video")

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
                     patch("backfill.decisions.time.sleep") as sleep:
                    destination = discard_as_weird(video)

            self.assertEqual(len(attempts), 2)
            sleep.assert_called_once()
            self.assertTrue(destination.is_file())

    def test_gives_up_on_a_clip_that_never_unlocks(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "kinda_weird"
            video = self._make_video(root)

            def always_locked(_self, _target):
                raise PermissionError(32, "The process cannot access the file")

            with override_config(WEIRD_DIR=weird_dir):
                with patch.object(type(video), "replace", always_locked), \
                     patch("backfill.decisions.time.sleep"):
                    with self.assertRaises(PermissionError):
                        discard_as_weird(video)


if __name__ == "__main__":
    unittest.main()
