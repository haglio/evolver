"""The Genau lane's last step: an upscaled loop leaves the outbox for Genau's folder."""

import unittest

from tasks import genau_deliver
from tests.temp_helpers import override_config, workspace_temp_dir

# Fabricated: the real folder name is library vocabulary and lives in the
# overlay, so a test names its own and overrides the config with it.
GENAU_SOURCE = "example-loop-clips"


def _lane(root):
    """The three folders the lane spans, wired into config for one test."""
    outbox = root / "2_outbox" / "upscaled_by_orientation"
    sorted_dir = root / "1_sorted"
    clips = root / "genau" / "clips"
    return outbox, sorted_dir, clips


def _stage_clip(outbox, sorted_dir, stem="loop_1", orient="landscape"):
    """One finished upscale in the outbox with the sorted video it was made from."""
    upscaled = outbox / orient / GENAU_SOURCE / f"{stem}_topaz.mp4"
    upscaled.parent.mkdir(parents=True, exist_ok=True)
    upscaled.write_text("upscaled", encoding="utf-8")
    original = sorted_dir / GENAU_SOURCE / orient / f"{stem}.mp4"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text("original", encoding="utf-8")
    return upscaled, original


class TestGenauDeliver(unittest.TestCase):
    def test_a_finished_clip_moves_to_genaus_folder(self):
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            upscaled, original = _stage_clip(outbox, sorted_dir)
            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                result = genau_deliver.run()

            self.assertEqual(result.delivered, 1)
            delivered = clips / "loop_1_topaz.mp4"
            self.assertTrue(delivered.is_file())
            self.assertEqual(delivered.read_text(encoding="utf-8"), "upscaled")
            self.assertFalse(upscaled.exists())
            # The source goes with it: left behind, the upscale stage would remake
            # this clip every run and the correspondence check would call it a
            # mismatch (see the module docstring).
            self.assertFalse(original.exists())

    def test_only_the_genau_source_is_delivered(self):
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            _stage_clip(outbox, sorted_dir)
            other = outbox / "landscape" / "origenerator" / "video_1_topaz.mp4"
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text("a library video", encoding="utf-8")
            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                result = genau_deliver.run()

            self.assertEqual(result.delivered, 1)
            self.assertTrue(other.is_file())  # the ordinary lane stays in the outbox
            self.assertFalse((clips / "video_1_topaz.mp4").exists())

    def test_clips_are_found_under_every_orientation(self):
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            _stage_clip(outbox, sorted_dir, stem="wide", orient="landscape")
            _stage_clip(outbox, sorted_dir, stem="tall", orient="portrait")
            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                result = genau_deliver.run()

            self.assertEqual(result.delivered, 2)
            self.assertTrue((clips / "wide_topaz.mp4").is_file())
            self.assertTrue((clips / "tall_topaz.mp4").is_file())

    def test_a_name_already_in_genaus_folder_is_not_overwritten(self):
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            _stage_clip(outbox, sorted_dir)
            clips.mkdir(parents=True)
            existing = clips / "loop_1_topaz.mp4"
            existing.write_text("a clip already being played", encoding="utf-8")
            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                genau_deliver.run()

            self.assertEqual(existing.read_text(encoding="utf-8"),
                             "a clip already being played")
            self.assertTrue((clips / "loop_1_topaz (2).mp4").is_file())

    def test_a_clip_that_cannot_be_moved_is_left_whole_for_the_next_run(self):
        # Genau holds the file open on Windows while it plays. Leaving both halves
        # in place keeps the outbox consistent, and the next run delivers it.
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            upscaled, original = _stage_clip(outbox, sorted_dir)

            def _locked(self, target):
                raise OSError("the file is in use")

            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                original_replace = type(upscaled).replace
                type(upscaled).replace = _locked
                try:
                    result = genau_deliver.run()
                finally:
                    type(upscaled).replace = original_replace

            self.assertEqual((result.delivered, result.failed), (0, 1))
            self.assertTrue(upscaled.is_file())
            self.assertTrue(original.is_file())

    def test_an_empty_lane_is_a_no_op(self):
        with workspace_temp_dir() as root:
            outbox, sorted_dir, clips = _lane(root)
            with override_config(OUT_UPSCALED_DIR=outbox, SORTED_DIR=sorted_dir,
                                 GENAU_CLIPS_DIR=clips, GENAU_SOURCE=GENAU_SOURCE,
                                 METADATA_DIR=root / "metadata"):
                result = genau_deliver.run()

            self.assertEqual((result.delivered, result.failed), (0, 0))
            self.assertFalse(clips.exists())  # nothing to deliver, nothing created


if __name__ == "__main__":
    unittest.main()
