import unittest
from pathlib import Path

from tasks import nonai_group
from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar


def _touch(path: Path, body: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


class TestNonAiGroup(unittest.TestCase):
    def test_writes_a_sidecar_per_clip_folding_variants(self):
        with workspace_temp_dir() as root:
            non_ai, metadata = root / "non_AI", root / "metadata"
            with override_config(NON_AI_DIR=non_ai, METADATA_DIR=metadata):
                original = _touch(non_ai / "larkin" / "2 done" / "Jane Doe-lA0JUsAd.mp4")
                variant = _touch(
                    non_ai / "larkin" / "3_good_to_go" / "processed"
                    / "Jane Doe-lA0JUsAd_3_apf2_iris2.mp4"
                )
                other = _touch(non_ai / "larkin" / "0 unsorted" / "Ada Roe-1.mp4")

                result = nonai_group.run()

                orig = sidecar.read(sidecar.nonai_sidecar_path(original))
                var = sidecar.read(sidecar.nonai_sidecar_path(variant))
                distinct = sidecar.read(sidecar.nonai_sidecar_path(other))
                self.assertEqual(orig["version"]["group"], var["version"]["group"])
                self.assertNotEqual(orig["version"]["group"], distinct["version"]["group"])
                self.assertFalse(orig["version"]["processed"])
                self.assertTrue(var["version"]["processed"])
                self.assertEqual(result.written, 3)

    def test_leaves_the_excluded_bucket_alone(self):
        with workspace_temp_dir() as root:
            non_ai, metadata = root / "non_AI", root / "metadata"
            with override_config(
                NON_AI_DIR=non_ai, METADATA_DIR=metadata,
                NONAI_EXCLUDED_BUCKETS={"actually_AI_but_funscripted"},
            ):
                clip = _touch(non_ai / "actually_AI_but_funscripted" / "landscape" / "x_topaz.mp4")
                nonai_group.run()
                self.assertFalse(sidecar.nonai_sidecar_path(clip).exists())

    def test_is_idempotent_then_prunes_a_removed_clips_sidecar(self):
        with workspace_temp_dir() as root:
            non_ai, metadata = root / "non_AI", root / "metadata"
            with override_config(NON_AI_DIR=non_ai, METADATA_DIR=metadata):
                clip = _touch(non_ai / "larkin" / "0 unsorted" / "Scene-1.mp4")
                self.assertEqual(nonai_group.run().written, 1)
                self.assertEqual(nonai_group.run().written, 0)  # nothing changed

                clip.unlink()
                result = nonai_group.run()
                self.assertEqual(result.pruned, 1)
                self.assertFalse(sidecar.nonai_sidecar_path(clip).exists())


if __name__ == "__main__":
    unittest.main()
