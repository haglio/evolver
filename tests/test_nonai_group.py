import unittest
from pathlib import Path

from tasks import nonai_group
from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar


def _touch(path: Path, body: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _library(root: Path) -> tuple[Path, Path, Path]:
    """A (video_library, non_AI, metadata) triple mirroring the real layout."""
    video_lib = root / "videos"
    non_ai = video_lib / "2D" / "non_AI"
    metadata = root / "metadata"
    return video_lib, non_ai, metadata


class TestNonAiGroup(unittest.TestCase):
    def test_writes_a_sidecar_per_clip_folding_variants(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                original = _touch(non_ai / "winston" / "2 done" / "Jane-Doe-lA0JUsAd.mp4")
                variant = _touch(
                    non_ai / "winston" / "3_good_to_go" / "processed"
                    / "Jane-Doe-lA0JUsAd_3_apf2_iris2.mp4"
                )
                other = _touch(non_ai / "winston" / "0 unsorted" / "Ada-Roe-1.mp4")

                result = nonai_group.run()

                # The sidecar mirrors the clip's full path under metadata/.
                self.assertEqual(
                    sidecar.sidecar_path(original),
                    metadata / "2D" / "non_AI" / "winston" / "2 done" / "Jane-Doe-lA0JUsAd.json",
                )
                orig = sidecar.read(sidecar.sidecar_path(original))
                var = sidecar.read(sidecar.sidecar_path(variant))
                distinct = sidecar.read(sidecar.sidecar_path(other))
                self.assertEqual(orig["version"]["group"], var["version"]["group"])
                self.assertNotEqual(orig["version"]["group"], distinct["version"]["group"])
                self.assertFalse(orig["version"]["processed"])
                self.assertTrue(var["version"]["processed"])
                self.assertEqual(result.written, 3)

    def test_leaves_the_excluded_bucket_alone(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata,
                NONAI_EXCLUDED_BUCKETS={"actually_AI_but_funscripted"},
            ):
                clip = _touch(non_ai / "actually_AI_but_funscripted" / "landscape" / "x_topaz.mp4")
                nonai_group.run()
                self.assertFalse(sidecar.sidecar_path(clip).exists())

    def test_merges_version_into_an_existing_clip_sidecar(self):
        """A clip carved from a compilation carries a `clip` object; grouping must
        add `version` alongside it, never clobber it."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "winston" / "1 clips" / "Kim Lee - POV.mp4")
                sidecar.write(
                    sidecar.sidecar_path(clip),
                    {"video": {"action": "Alpha"},
                     "clip": {"compilation": "Vol6", "index": 9}},
                )

                nonai_group.run()

                got = sidecar.read(sidecar.sidecar_path(clip))
                self.assertEqual(got["clip"], {"compilation": "Vol6", "index": 9})
                self.assertEqual(got["video"], {"action": "Alpha"})
                self.assertIn("group", got["version"])

    def test_propagates_clip_across_the_version_family(self):
        """The upscaled variant of a clip inherits the original's `clip` metadata,
        so Nau still treats the enhanced file as a navigable short."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                original = _touch(non_ai / "winston" / "2 done" / "Lee-Poe.mp4")
                variant = _touch(
                    non_ai / "winston" / "3_good_to_go" / "processed"
                    / "Lee-Poe_apo8_iris2.mp4"
                )
                sidecar.write(
                    sidecar.sidecar_path(original),
                    {"clip": {"compilation": "Vol6", "index": 1}},
                )

                nonai_group.run()

                var = sidecar.read(sidecar.sidecar_path(variant))
                self.assertEqual(var["clip"], {"compilation": "Vol6", "index": 1})

    def test_does_not_tag_a_name_neighbour_as_a_clip(self):
        """A family is name-derived, so a full scene the user already owned can
        share one with a clip carved from the same movie. Only true re-encodes of
        the clip inherit its `clip` object — never the neighbour."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "winston" / "1 clips" / "Kim Lee - POV Scene Two.mp4")
                upscaled = _touch(
                    non_ai / "winston" / "3_good_to_go" / "processed"
                    / "Kim Lee - POV Scene Two_apo8_iris2.mp4"
                )
                neighbour = _touch(
                    non_ai / "winston" / "0 unsorted"
                    / "Kim Lee - POV Scene Two (2009) Enhanced.mp4"
                )
                sidecar.write(sidecar.sidecar_path(clip), {"clip": {"compilation": "Vol6", "index": 9}})

                nonai_group.run()

                self.assertIn("clip", sidecar.read(sidecar.sidecar_path(upscaled)))
                self.assertNotIn("clip", sidecar.read(sidecar.sidecar_path(neighbour)))

    def test_a_declared_pair_gets_one_group_the_names_never_would(self):
        """The stage rewrites `version.group` every run, so a hand edit to a
        sidecar lasts ten minutes. Declaring the pair is what makes it stick."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata,
                NONAI_VERSION_OVERRIDES={
                    "redacted POV BJ 4k 60fps": "redacted_540-pacI21CK",
                },
            ):
                original = _touch(non_ai / "winston" / "0 unsorted" / "redacted_540-pacI21CK.mp4")
                upscale = _touch(
                    non_ai / "winston" / "3_good_to_go" / "processed"
                    / "redacted POV BJ 4k 60fps.mp4"
                )

                nonai_group.run()

                self.assertEqual(
                    sidecar.read(sidecar.sidecar_path(upscale))["version"]["group"],
                    sidecar.read(sidecar.sidecar_path(original))["version"]["group"],
                )

    def test_is_idempotent_then_prunes_a_removed_clips_sidecar(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "winston" / "0 unsorted" / "Scene-1.mp4")
                self.assertEqual(nonai_group.run().written, 1)
                self.assertEqual(nonai_group.run().written, 0)  # nothing changed

                clip.unlink()
                result = nonai_group.run()
                self.assertEqual(result.pruned, 1)
                self.assertFalse(sidecar.sidecar_path(clip).exists())


if __name__ == "__main__":
    unittest.main()
