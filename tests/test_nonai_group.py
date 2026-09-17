from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import evolver
from tasks import nonai_group
from tests.temp_helpers import override_config, workspace_temp_dir, write_sidecar
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
                original = _touch(non_ai / "larkin" / "2 done" / "Jane-Doe-lA0JUsAd.mp4")
                variant = _touch(
                    non_ai / "larkin" / "3_good_to_go" / "processed"
                    / "Jane-Doe-lA0JUsAd_3_apf2_iris2.mp4"
                )
                other = _touch(non_ai / "larkin" / "0 unsorted" / "Ada-Roe-1.mp4")

                result = nonai_group.run()

                # The sidecar mirrors the clip's full path under metadata/.
                self.assertEqual(
                    sidecar.sidecar_path(original),
                    metadata / "2D" / "non_AI" / "larkin" / "2 done" / "Jane-Doe-lA0JUsAd.json",
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
                clip = _touch(non_ai / "larkin" / "1 clips" / "Ann Bly - POV.mp4")
                write_sidecar(
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
        so the main player still treats the enhanced file as a navigable short."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                original = _touch(non_ai / "larkin" / "2 done" / "Lee-Poe.mp4")
                variant = _touch(
                    non_ai / "larkin" / "3_good_to_go" / "processed"
                    / "Lee-Poe_apo8_iris2.mp4"
                )
                write_sidecar(
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
                clip = _touch(non_ai / "larkin" / "1 clips" / "Ann Bly - Scene Two.mp4")
                upscaled = _touch(
                    non_ai / "larkin" / "3_good_to_go" / "processed"
                    / "Ann Bly - Scene Two_apo8_iris2.mp4"
                )
                neighbour = _touch(
                    non_ai / "larkin" / "0 unsorted"
                    / "Ann Bly - Scene Two (2009) Enhanced.mp4"
                )
                write_sidecar(sidecar.sidecar_path(clip), {"clip": {"compilation": "Vol6", "index": 9}})

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
                    "Jane Doe Scene Two 4k 60fps": "jane-doe_540-Qv3Tn8Rd",
                },
            ):
                original = _touch(non_ai / "larkin" / "0 unsorted" / "jane-doe_540-Qv3Tn8Rd.mp4")
                upscale = _touch(
                    non_ai / "larkin" / "3_good_to_go" / "processed"
                    / "Jane Doe Scene Two 4k 60fps.mp4"
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
                clip = _touch(non_ai / "larkin" / "0 unsorted" / "Scene-1.mp4")
                self.assertEqual(nonai_group.run().written, 1)
                self.assertEqual(nonai_group.run().written, 0)  # nothing changed

                clip.unlink()
                result = nonai_group.run()
                self.assertEqual(result.pruned, 1)
                self.assertFalse(sidecar.sidecar_path(clip).exists())


ONE_PICTURE = [f"{0x5A5A5A5A5A5A5A5A + moment:016x}" for moment in range(16)]


def _scene(path: Path, seconds: float) -> Path:
    """A full-length video whose running time the video-kinds stage has recorded."""
    _touch(path)
    write_sidecar(sidecar.sidecar_path(path),
                  {"video": {"type": "full_length", "duration_seconds": seconds}})
    return path


def _group(video: Path) -> str:
    return sidecar.read(sidecar.sidecar_path(video))["version"]["group"]


class TestOneVideoByItsPictures(unittest.TestCase):
    def test_two_differently_named_copies_with_the_same_pictures_are_one_video(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "larkin" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)

                result = nonai_group.run(fingerprint=lambda video, seconds: ONE_PICTURE)

                self.assertEqual(_group(old), _group(new))
                self.assertEqual(result.joined, 1)

    def test_a_video_is_measured_once_and_its_pictures_kept(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "larkin" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_PICTURE

                nonai_group.run(fingerprint=fingerprint)
                nonai_group.run(fingerprint=fingerprint)

                self.assertEqual(sorted(measured), sorted([old.name, new.name]))
                self.assertEqual(_group(old), _group(new))

    def test_only_full_videos_of_the_same_length_are_ever_measured(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "larkin" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)
                longer = _scene(unsorted / "Jane Doe - Scene Three.mp4", 851.2)
                carved = _touch(non_ai / "larkin" / "1 clips" / "Jane Doe - Scene Two.mp4")
                write_sidecar(sidecar.sidecar_path(carved), {
                    "clip": {"compilation": "Vol6", "index": 2},
                    "video": {"type": "excerpt", "duration_seconds": 850.5},
                })
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_PICTURE

                nonai_group.run(fingerprint=fingerprint)

                self.assertEqual(sorted(measured), sorted([old.name, new.name]))
                self.assertNotEqual(_group(longer), _group(old))
                self.assertNotEqual(_group(carved), _group(old))

    def test_a_family_is_measured_through_its_smallest_file(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                bucket = non_ai / "larkin"
                old = _scene(bucket / "0 unsorted" / "Jane Doe - studio video original.mp4", 850.57)
                upscale = _scene(bucket / "3_good_to_go" / "processed"
                                 / "Jane Doe - studio video original_apo8_iris2.mp4", 850.57)
                upscale.write_text("x" * 50)
                new = _scene(bucket / "0 unsorted" / "jane-doe-scene-two-enhanced.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_PICTURE

                nonai_group.run(fingerprint=fingerprint)

                self.assertEqual(sorted(measured), sorted([old.name, new.name]))
                self.assertEqual(_group(upscale), _group(new))

    def test_pictures_an_upscale_was_handed_are_not_measured_again(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                bucket = non_ai / "larkin"
                upscale = bucket / "3_good_to_go" / "processed" / "Jane Doe - original_apo8_iris2.mp4"
                _touch(upscale)
                write_sidecar(sidecar.sidecar_path(upscale), {
                    "video": {"type": "full_length", "duration_seconds": 850.57},
                    "footage": {"fingerprint": ONE_PICTURE},
                })
                new = _scene(bucket / "0 unsorted" / "jane-doe-scene-two-enhanced.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_PICTURE

                nonai_group.run(fingerprint=fingerprint)

                self.assertEqual(measured, [new.name])
                self.assertEqual(_group(upscale), _group(new))

    def test_a_run_measures_no_more_videos_than_its_allowance(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ), patch.object(nonai_group, "MEASURED_PER_RUN", 3):
                unsorted = non_ai / "larkin" / "0 unsorted"
                for scene, seconds in ((1, 100.0), (2, 200.0), (3, 300.0)):
                    _scene(unsorted / f"Jane Doe - Scene {scene}.mp4", seconds)
                    _scene(unsorted / f"jane-doe-copy-{scene}-enhanced.mp4", seconds + 0.1)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_PICTURE

                result = nonai_group.run(fingerprint=fingerprint)

                self.assertEqual(len(measured), 3)
                self.assertEqual(result.measured, 3)

    def test_the_same_length_with_other_pictures_is_another_video(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "larkin" / "0 unsorted"
                first = _scene(unsorted / "various - Example Studio - finale 1.mp4", 60.0)
                second = _scene(unsorted / "various - Example Studio - finale 2.mp4", 59.95)
                other = [f"{int(moment, 16) ^ ((1 << 64) - 1):016x}" for moment in ONE_PICTURE]

                nonai_group.run(fingerprint=lambda video, seconds:
                                ONE_PICTURE if video == first else other)

                self.assertNotEqual(_group(first), _group(second))


class TestGroupingCannotFail(unittest.TestCase):
    def test_the_verdict_rule_lives_in_the_table_and_nowhere_else(self):
        """Grouping is bookkeeping over whatever files exist: absence from
        ``_STAGE_FAILED`` is what says it cannot fail, so a result that also
        advertises an ``ok`` invites a reader to look in the wrong place."""
        self.assertNotIn("group_non_ai", evolver._STAGE_FAILED)
        self.assertFalse(hasattr(nonai_group.NonAiGroupResult(), "ok"))


if __name__ == "__main__":
    unittest.main()
