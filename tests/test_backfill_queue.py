from __future__ import annotations

import unittest
from pathlib import Path

from backfill.queue import BackfillQueue, unlabeled_clips
from tests.temp_helpers import library_tree, override_config


class TestUnlabeledVideos(unittest.TestCase):
    def test_a_video_with_no_sidecar_is_unlabeled(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider2", "a_topaz.mp4")

            assert unlabeled_clips() == [video]

    def test_a_sidecar_without_an_action_leaves_the_video_unlabeled(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider2", "a_topaz.mp4")
            lib.sidecar("portrait", "provider2", "a_topaz", {"video": {"prompt": "p"}})

            assert unlabeled_clips() == [video]

    def test_a_sidecar_with_an_action_labels_the_video(self):
        with library_tree() as lib:
            lib.video("portrait", "provider2", "a_topaz.mp4")
            lib.sidecar("portrait", "provider2", "a_topaz", {"video": {"action": "Alpha"}})

            assert unlabeled_clips() == []

    def test_the_scraped_sources_are_never_offered(self):
        with library_tree() as lib:
            lib.video("portrait", "provider", "a_topaz.mp4")
            lib.video("landscape", "origenerator", "b_topaz.mp4")

            assert unlabeled_clips() == []

    def test_the_scraped_provider_is_whoever_the_overlay_names(self):
        # The provider's source name is the overlay's, and the deployed one is
        # not the committed placeholder: compared against a literal, every one
        # of the real provider's unlabeled clips was queued for dictation --
        # exactly what the skip exists to prevent (bug 12).
        with library_tree() as lib, override_config(PROVIDER_SOURCE="examplesource"):
            lib.video("portrait", "examplesource", "a_topaz.mp4")
            placeholder = lib.video("portrait", "provider", "b_topaz.mp4")

            assert unlabeled_clips() == [placeholder]

    def test_a_half_written_upscale_is_never_offered(self):
        with library_tree() as lib:
            lib.video("portrait", "provider2", "a.partial.deadbeef.mp4")

            assert unlabeled_clips() == []

    def test_a_clip_whose_act_was_called_wrong_is_asked_about_first(self):
        """Fun Time strikes a mislabeled act out of the sidecar and leaves
        ``wrong_action`` in its place.  Someone said that clip is wrong *just now*, so
        it goes to the head of the queue rather than the back of a library walk
        they may never reach."""
        with library_tree() as lib:
            # The rejected clip sits last in the library walk (portrait sweeps
            # before landscape), so only a reordering can bring it to the front.
            plain = lib.video("portrait", "provider2", "a_topaz.mp4")
            rejected = lib.video("landscape", "provider2", "b_topaz.mp4")
            lib.sidecar("landscape", "provider2", "b_topaz",
                               {"video": {"prompt": "p", "wrong_action": "Alpha"}})

            assert unlabeled_clips() == [rejected, plain]

    def test_a_scraped_clip_whose_act_was_called_wrong_is_offered_anyway(self):
        """A scraped act is skipped because the scrape stage knows what the clip
        shows — which is exactly the claim a viewer has just contradicted, and
        the stage cannot correct itself."""
        with library_tree() as lib:
            rejected = lib.video("portrait", "origenerator", "a_topaz.mp4")
            lib.sidecar("portrait", "origenerator", "a_topaz",
                               {"video": {"wrong_action": "Alpha"}})

            assert unlabeled_clips() == [rejected]

    def test_both_orientations_are_swept(self):
        with library_tree() as lib:
            portrait = lib.video("portrait", "provider2", "a_topaz.mp4")
            landscape = lib.video("landscape", "provider3", "b_topaz.mp4")

            assert sorted(unlabeled_clips()) == sorted([portrait, landscape])


class TestBackfillQueue(unittest.TestCase):
    def _queue(self, count):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        return BackfillQueue(videos)

    def test_remaining_counts_every_video_still_needing_an_action(self):
        queue = self._queue(3)
        assert queue.remaining == 3

    def test_resolving_the_current_video_drops_it(self):
        queue = self._queue(3)
        first = queue.current

        queue.resolve()

        assert queue.remaining == 2
        assert queue.current != first

    def test_deferring_sends_the_current_video_to_the_back(self):
        queue = self._queue(3)
        first = queue.current

        queue.defer()

        assert queue.remaining == 3
        assert queue.current != first
        queue.resolve()
        queue.resolve()
        assert queue.current == first

    def test_deferring_the_only_video_leaves_it_on_screen(self):
        queue = self._queue(1)
        only = queue.current

        queue.defer()

        assert queue.current == only
        assert queue.remaining == 1

    def test_current_is_none_once_every_video_is_resolved(self):
        queue = self._queue(1)

        queue.resolve()

        assert queue.current is None
        assert queue.remaining == 0

    def test_restoring_puts_a_resolved_video_back_on_screen(self):
        queue = self._queue(3)
        first = queue.current
        queue.resolve()

        queue.restore(first)

        assert queue.current == first
        assert queue.remaining == 3

    def test_undeferring_brings_a_skipped_video_back_to_the_front(self):
        queue = self._queue(3)
        first = queue.current
        queue.defer()

        queue.undefer()

        assert queue.current == first
        assert queue.remaining == 3

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
        assert rewound == original

    def test_the_queue_keeps_the_order_it_was_given(self):
        """Stable order is what lets a reopened session resume where it left off."""
        videos = [Path(f"clip{i}.mp4") for i in range(10)]

        queue = BackfillQueue(videos)

        drained = []
        while queue.current is not None:
            drained.append(queue.current)
            queue.resolve()
        assert drained == videos


if __name__ == "__main__":
    unittest.main()
