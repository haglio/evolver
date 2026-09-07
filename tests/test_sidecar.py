import threading
import unittest

from app_support.json_store import locked_update

from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar
from util.sidecar import WRONG_ACTION_FIELD, sidecar_path, upscaled_video_path


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
                video_lib / "2D" / "non_AI" / "larkin" / "3_good_to_go" / "processed"
                / "clip_apo8_iris2.mp4"
            )

            with override_config(VIDEO_LIBRARY_DIR=video_lib, METADATA_DIR=metadata):
                self.assertEqual(
                    sidecar_path(video),
                    metadata / "2D" / "non_AI" / "larkin" / "3_good_to_go" / "processed"
                    / "clip_apo8_iris2.json",
                )

    def test_mirrors_a_genau_clip_from_beside_the_library(self):
        """Genau's clips sit next to the video tree rather than inside it, so
        they mirror from the folder that holds both."""
        with workspace_temp_dir() as root:
            videos = root / "videos"
            metadata = root / "metadata"

            with override_config(
                VIDEO_LIBRARY_DIR=videos / "videos", VIDEO_SEARCH_ROOT=videos,
                METADATA_DIR=metadata,
            ):
                self.assertEqual(
                    sidecar_path(videos / "genau" / "clips" / "loop.mp4"),
                    metadata / "genau" / "clips" / "loop.json",
                )

    def test_rejects_a_video_outside_the_library(self):
        with workspace_temp_dir() as root, override_config(
            VIDEO_LIBRARY_DIR=root / "videos" / "videos",
            VIDEO_SEARCH_ROOT=root / "videos", METADATA_DIR=root / "metadata",
        ), self.assertRaises(ValueError):
            sidecar_path(root / "elsewhere" / "clip.mp4")


class TestUpdate(unittest.TestCase):
    """The one write, and the lock it holds while it reads and changes.

    Two apps write these documents -- this app's pipeline on a ten-minute
    timer, Fun Time the moment a viewer strikes an act out -- and each used to
    read, change and write on its own, so whichever wrote second erased the
    field the first had just put in.
    """

    def test_no_other_writer_gets_in_while_one_is_inside(self):
        """The lock is taken on the document's own name, which is the name Fun
        Time's writer takes: it is kept out, rather than writing alongside."""
        with workspace_temp_dir() as root:
            path = root / "clip.json"
            refused = []

            def look_for_a_way_in(payload):
                try:
                    locked_update(path, lambda other: other, wait_s=0)
                except TimeoutError:
                    refused.append(True)
                return {"video": {"action": "alpha"}}

            sidecar.update(path, look_for_a_way_in)

            self.assertEqual(refused, [True])

    def test_it_changes_the_document_the_other_writer_left(self):
        """The lost update itself: a pass whose turn comes after a rejection
        writes onto the rejection, not onto what it read before waiting."""
        with workspace_temp_dir() as root:
            path = root / "clip.json"
            sidecar.update(path, lambda _: {"video": {"action": "alpha"}})
            inside = threading.Event()
            let_go = threading.Event()

            def strike_the_act_out(payload):
                inside.set()
                let_go.wait(5)
                return {"video": {WRONG_ACTION_FIELD: payload["video"]["action"]}}

            viewer = threading.Thread(
                target=locked_update, args=(path, strike_the_act_out), daemon=True)
            viewer.start()
            self.assertTrue(inside.wait(5))
            stamped = []
            pipeline = threading.Thread(
                target=lambda: stamped.append(
                    sidecar.update(path, lambda payload: {**payload, "favorite": True})),
                daemon=True)
            pipeline.start()
            let_go.set()
            viewer.join(5)
            pipeline.join(5)

            self.assertEqual(
                sidecar.read(path),
                {"video": {WRONG_ACTION_FIELD: "alpha"}, "favorite": True},
            )
            self.assertEqual(stamped, [sidecar.read(path)])

    def test_a_writer_with_nothing_to_change_leaves_the_file_alone(self):
        with workspace_temp_dir() as root:
            path = root / "clip.json"
            sidecar.update(path, lambda _: {"video": {"action": "alpha"}})
            written = path.read_text(encoding="utf-8")

            self.assertIsNone(sidecar.update(path, lambda payload: None))
            self.assertEqual(path.read_text(encoding="utf-8"), written)


if __name__ == "__main__":
    unittest.main()
