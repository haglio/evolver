import unittest

from tests.temp_helpers import override_config, workspace_temp_dir
from util.sidecar import sidecar_path, upscaled_video_path


class TestUpscaledVideoPath(unittest.TestCase):
    def test_names_the_clip_the_upscale_stage_will_write(self):
        with workspace_temp_dir() as root:
            upscaled = root / "AI" / "2_outbox" / "upscaled_by_orientation"

            with override_config(OUT_UPSCALED_DIR=upscaled):
                self.assertEqual(
                    upscaled_video_path("provider2", "portrait", "clip"),
                    upscaled / "portrait" / "provider2" / "clip_topaz.mp4",
                )


class TestSidecarPath(unittest.TestCase):
    def test_mirrors_an_ai_video_path_into_the_metadata_tree(self):
        with workspace_temp_dir() as root:
            video_lib = root / "videos"
            metadata = root / "metadata"
            video = (
                video_lib / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation"
                / "portrait" / "provider2" / "clip_topaz.mp4"
            )

            with override_config(VIDEO_LIBRARY_DIR=video_lib, METADATA_DIR=metadata):
                self.assertEqual(
                    sidecar_path(video),
                    metadata / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation"
                    / "portrait" / "provider2" / "clip_topaz.json",
                )

    def test_also_mirrors_a_non_ai_video_into_the_same_tree(self):
        with workspace_temp_dir() as root:
            video_lib = root / "videos"
            metadata = root / "metadata"
            video = (
                video_lib / "2D" / "non_AI" / "winston" / "3_good_to_go" / "processed"
                / "clip_apo8_iris2.mp4"
            )

            with override_config(VIDEO_LIBRARY_DIR=video_lib, METADATA_DIR=metadata):
                self.assertEqual(
                    sidecar_path(video),
                    metadata / "2D" / "non_AI" / "winston" / "3_good_to_go" / "processed"
                    / "clip_apo8_iris2.json",
                )

    def test_rejects_a_video_outside_the_library(self):
        with workspace_temp_dir() as root:
            with override_config(VIDEO_LIBRARY_DIR=root / "videos", METADATA_DIR=root / "metadata"):
                with self.assertRaises(ValueError):
                    sidecar_path(root / "elsewhere" / "clip.mp4")


if __name__ == "__main__":
    unittest.main()
