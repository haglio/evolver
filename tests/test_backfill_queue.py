import json
import random
import unittest
from pathlib import Path

from backfill.queue import BackfillQueue, unlabeled_videos
from tests.temp_helpers import override_config, workspace_temp_dir


class TestUnlabeledVideos(unittest.TestCase):
    def _tree(self, root):
        ai = root / "AI"
        return ai, ai / "2_outbox" / "upscaled_by_orientation", root / "metadata"

    def _make_video(self, upscaled, orient, source, name):
        video = upscaled / orient / source / name
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def _make_sidecar(self, metadata, orient, source, stem, payload):
        path = metadata / "2_outbox" / "upscaled_by_orientation" / orient / source / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_a_video_with_no_sidecar_is_unlabeled(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled, "portrait", "provider2", "a_topaz.mp4")

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(unlabeled_videos(), [video])

    def test_a_sidecar_without_an_action_leaves_the_video_unlabeled(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._make_video(upscaled, "portrait", "provider2", "a_topaz.mp4")
            self._make_sidecar(metadata, "portrait", "provider2", "a_topaz", {"video": {"prompt": "p"}})

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(unlabeled_videos(), [video])

    def test_a_sidecar_with_an_action_labels_the_video(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            self._make_video(upscaled, "portrait", "provider2", "a_topaz.mp4")
            self._make_sidecar(metadata, "portrait", "provider2", "a_topaz", {"video": {"action": "Alpha"}})

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(unlabeled_videos(), [])

    def test_the_scraped_sources_are_never_offered(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            self._make_video(upscaled, "portrait", "provider", "a_topaz.mp4")
            self._make_video(upscaled, "landscape", "origenerator", "b_topaz.mp4")

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(unlabeled_videos(), [])

    def test_a_half_written_upscale_is_never_offered(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            self._make_video(upscaled, "portrait", "provider2", "a.partial.deadbeef.mp4")

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(unlabeled_videos(), [])

    def test_both_orientations_are_swept(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            portrait = self._make_video(upscaled, "portrait", "provider2", "a_topaz.mp4")
            landscape = self._make_video(upscaled, "landscape", "provider3", "b_topaz.mp4")

            with override_config(AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(sorted(unlabeled_videos()), sorted([portrait, landscape]))


class TestBackfillQueue(unittest.TestCase):
    def _queue(self, count, seed=0):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        return BackfillQueue(videos, rng=random.Random(seed))

    def test_remaining_counts_every_video_still_needing_an_action(self):
        queue = self._queue(3)
        self.assertEqual(queue.remaining, 3)

    def test_resolving_the_current_video_drops_it(self):
        queue = self._queue(3)
        first = queue.current

        queue.resolve()

        self.assertEqual(queue.remaining, 2)
        self.assertNotEqual(queue.current, first)

    def test_deferring_sends_the_current_video_to_the_back(self):
        queue = self._queue(3)
        first = queue.current

        queue.defer()

        self.assertEqual(queue.remaining, 3)
        self.assertNotEqual(queue.current, first)
        queue.resolve()
        queue.resolve()
        self.assertEqual(queue.current, first)

    def test_deferring_the_only_video_leaves_it_on_screen(self):
        queue = self._queue(1)
        only = queue.current

        queue.defer()

        self.assertEqual(queue.current, only)
        self.assertEqual(queue.remaining, 1)

    def test_current_is_none_once_every_video_is_resolved(self):
        queue = self._queue(1)

        queue.resolve()

        self.assertIsNone(queue.current)
        self.assertEqual(queue.remaining, 0)

    def test_restoring_puts_a_resolved_video_back_on_screen(self):
        queue = self._queue(3)
        first = queue.current
        queue.resolve()

        queue.restore(first)

        self.assertEqual(queue.current, first)
        self.assertEqual(queue.remaining, 3)

    def test_undeferring_brings_a_skipped_video_back_to_the_front(self):
        queue = self._queue(3)
        first = queue.current
        queue.defer()

        queue.undefer()

        self.assertEqual(queue.current, first)
        self.assertEqual(queue.remaining, 3)

    def test_undoing_a_run_of_decisions_rewinds_the_original_order(self):
        queue = self._queue(4)
        original = []
        while queue.current is not None:
            original.append(queue.current)
            queue.resolve()

        for clip in reversed(original):
            queue.restore(clip)

        rewound = []
        while queue.current is not None:
            rewound.append(queue.current)
            queue.resolve()
        self.assertEqual(rewound, original)

    def test_a_seeded_shuffle_reorders_the_videos(self):
        videos = [Path(f"clip{i}.mp4") for i in range(10)]

        queue = BackfillQueue(videos, rng=random.Random(0))

        drained = []
        while queue.current is not None:
            drained.append(queue.current)
            queue.resolve()
        self.assertEqual(sorted(drained), sorted(videos))
        self.assertNotEqual(drained, videos)


if __name__ == "__main__":
    unittest.main()
