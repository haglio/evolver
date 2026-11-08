from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import nonai_group
from tests.temp_helpers import LaneLibrary, override_config, workspace_temp_dir, write_sidecar
from util import sidecar


def _touch(path: Path, body: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _library(root: Path) -> tuple[Path, Path, Path]:
    video_lib = root / "videos"
    non_ai = video_lib / "2D" / "non_AI"
    metadata = root / "metadata"
    return video_lib, non_ai, metadata


class TestNonAiGroup(unittest.TestCase):
    def test_writes_a_sidecar_per_clip_folding_versions(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                original = _touch(non_ai / "lagoon" / "2 done" / "Jane-Doe-lA0JUsAd.mp4")
                version = _touch(
                    non_ai / "lagoon" / "3_good_to_go" / "processed"
                    / "Jane-Doe-lA0JUsAd_3_apf2_iris2.mp4"
                )
                other = _touch(non_ai / "lagoon" / "0 unsorted" / "Ada-Roe-1.mp4")

                result = nonai_group.run()

                assert sidecar.sidecar_path(original) == metadata / "2D" / "non_AI" / "lagoon" / "2 done" / "Jane-Doe-lA0JUsAd.json"
                orig = sidecar.read(sidecar.sidecar_path(original))
                var = sidecar.read(sidecar.sidecar_path(version))
                distinct = sidecar.read(sidecar.sidecar_path(other))
                assert orig["version"]["group"] == var["version"]["group"]
                assert orig["version"]["group"] != distinct["version"]["group"]
                assert not orig["version"]["processed"]
                assert var["version"]["processed"]
                assert result.written == 3

    def test_merges_version_into_an_existing_clip_sidecar(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "lagoon" / "1 clips" / "Ann Bly - Scene One.mp4")
                write_sidecar(
                    sidecar.sidecar_path(clip),
                    {"video": {"action": "Alpha"},
                     "clip": {"compilation": "Vol6", "index": 9}},
                )

                nonai_group.run()

                got = sidecar.read(sidecar.sidecar_path(clip))
                assert got["clip"] == {"compilation": "Vol6", "index": 9}
                assert got["video"] == {"action": "Alpha"}
                assert "group" in got["version"]

    def test_propagates_clip_across_the_version_family(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                original = _touch(non_ai / "lagoon" / "2 done" / "Lee-Poe.mp4")
                version = _touch(
                    non_ai / "lagoon" / "3_good_to_go" / "processed"
                    / "Lee-Poe_apo8_iris2.mp4"
                )
                write_sidecar(
                    sidecar.sidecar_path(original),
                    {"clip": {"compilation": "Vol6", "index": 1}},
                )

                nonai_group.run()

                var = sidecar.read(sidecar.sidecar_path(version))
                assert var["clip"] == {"compilation": "Vol6", "index": 1}

    def test_does_not_tag_a_name_neighbour_as_a_clip(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "lagoon" / "1 clips" / "Ann Bly - Scene Two.mp4")
                upscaled = _touch(
                    non_ai / "lagoon" / "3_good_to_go" / "processed"
                    / "Ann Bly - Scene Two_apo8_iris2.mp4"
                )
                neighbour = _touch(
                    non_ai / "lagoon" / "0 unsorted"
                    / "Ann Bly - Scene Two (2009) Enhanced.mp4"
                )
                write_sidecar(sidecar.sidecar_path(clip), {"clip": {"compilation": "Vol6", "index": 9}})

                nonai_group.run()

                assert "clip" in sidecar.read(sidecar.sidecar_path(upscaled))
                assert "clip" not in sidecar.read(sidecar.sidecar_path(neighbour))

    def test_a_declared_pair_gets_one_group_the_names_never_would(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata,
                NONAI_VERSION_OVERRIDES={
                    "Jane Doe Scene Two 4k 60fps": "jane-doe_540-Qv3Tn8Rd",
                },
            ):
                original = _touch(non_ai / "lagoon" / "0 unsorted" / "jane-doe_540-Qv3Tn8Rd.mp4")
                upscale = _touch(
                    non_ai / "lagoon" / "3_good_to_go" / "processed"
                    / "Jane Doe Scene Two 4k 60fps.mp4"
                )

                nonai_group.run()

                assert sidecar.read(sidecar.sidecar_path(upscale))["version"]["group"] == sidecar.read(sidecar.sidecar_path(original))["version"]["group"]

    def test_a_family_edited_by_hand_in_a_record_is_written_over_so_an_override_is_the_way(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai,
                                 METADATA_DIR=metadata):
                video = _touch(non_ai / "lagoon" / "0 unsorted" / "jane-doe_540-Qv3Tn8Rd.mp4")
                nonai_group.run()
                record = sidecar.sidecar_path(video)
                grouped = sidecar.read(record)["version"]["group"]
                write_sidecar(record, {"version": {"group": "edited by hand", "processed": False}})

                nonai_group.run()

                assert sidecar.read(record)["version"]["group"] == grouped

    def test_is_idempotent_then_prunes_a_removed_clips_sidecar(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "lagoon" / "0 unsorted" / "Scene-1.mp4")
                assert nonai_group.run().written == 1
                assert nonai_group.run().written == 0

                clip.unlink()
                result = nonai_group.run()
                assert result.pruned == 1
                assert not sidecar.sidecar_path(clip).exists()

    def test_keeps_the_record_of_a_clip_marked_trash_until_it_is_reviewed(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                clip = _touch(lib.non_ai / "example-bucket" / "0 unsorted" / "Scene-2.mp4")
                nonai_group.run()
                lib.trash.mkdir(parents=True)
                clip.replace(lib.trash / f"{clip.stem}__dup1{clip.suffix}")

                result = nonai_group.run()

                assert result.pruned == 0
                assert sidecar.sidecar_path(clip).exists()


ONE_FINGERPRINT = [f"{0x5A5A5A5A5A5A5A5A + moment:016x}" for moment in range(16)]


def _scene(path: Path, seconds: float) -> Path:
    _touch(path)
    write_sidecar(sidecar.sidecar_path(path),
                  {"video": {"type": "full_length", "duration_seconds": seconds}})
    return path


def _group(video: Path) -> str:
    return sidecar.read(sidecar.sidecar_path(video))["version"]["group"]


class TestOneVideoByItsFrames(unittest.TestCase):
    def test_two_differently_named_copies_with_the_same_frames_are_one_video(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "lagoon" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)

                result = nonai_group.run(fingerprint=lambda video, seconds: ONE_FINGERPRINT)

                assert _group(old) == _group(new)
                assert result.joined == 1

    def test_a_video_is_measured_once_and_its_frames_kept(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "lagoon" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_FINGERPRINT

                nonai_group.run(fingerprint=fingerprint)
                nonai_group.run(fingerprint=fingerprint)

                assert sorted(measured) == sorted([old.name, new.name])
                assert _group(old) == _group(new)

    def test_only_full_videos_of_the_same_length_are_ever_measured(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "lagoon" / "0 unsorted"
                old = _scene(unsorted / "Jane Doe - studio video original.mp4", 850.57)
                new = _scene(unsorted / "jane-doe-scene-two-enhanced-60fps-1080p.mp4", 850.51)
                longer = _scene(unsorted / "Jane Doe - Scene Three.mp4", 851.2)
                carved = _touch(non_ai / "lagoon" / "1 clips" / "Jane Doe - Scene Two.mp4")
                write_sidecar(sidecar.sidecar_path(carved), {
                    "clip": {"compilation": "Vol6", "index": 2},
                    "video": {"type": "excerpt", "duration_seconds": 850.5},
                })
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_FINGERPRINT

                nonai_group.run(fingerprint=fingerprint)

                assert sorted(measured) == sorted([old.name, new.name])
                assert _group(longer) != _group(old)
                assert _group(carved) != _group(old)

    def test_a_family_is_measured_through_its_smallest_file(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                bucket = non_ai / "lagoon"
                old = _scene(bucket / "0 unsorted" / "Jane Doe - studio video original.mp4", 850.57)
                upscale = _scene(bucket / "3_good_to_go" / "processed"
                                 / "Jane Doe - studio video original_apo8_iris2.mp4", 850.57)
                upscale.write_text("x" * 50)
                new = _scene(bucket / "0 unsorted" / "jane-doe-scene-two-enhanced.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_FINGERPRINT

                nonai_group.run(fingerprint=fingerprint)

                assert sorted(measured) == sorted([old.name, new.name])
                assert _group(upscale) == _group(new)

    def test_frames_an_upscale_was_handed_are_not_measured_again(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                bucket = non_ai / "lagoon"
                upscale = bucket / "3_good_to_go" / "processed" / "Jane Doe - original_apo8_iris2.mp4"
                _touch(upscale)
                write_sidecar(sidecar.sidecar_path(upscale), {
                    "video": {"type": "full_length", "duration_seconds": 850.57},
                    "footage": {"fingerprint": ONE_FINGERPRINT},
                })
                new = _scene(bucket / "0 unsorted" / "jane-doe-scene-two-enhanced.mp4", 850.51)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_FINGERPRINT

                nonai_group.run(fingerprint=fingerprint)

                assert measured == [new.name]
                assert _group(upscale) == _group(new)

    def test_a_folder_arriving_at_once_costs_only_a_few_videos_of_decoding_a_run(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ), patch.object(nonai_group, "MEASURED_PER_RUN", 3):
                unsorted = non_ai / "lagoon" / "0 unsorted"
                for scene, seconds in ((1, 100.0), (2, 200.0), (3, 300.0)):
                    _scene(unsorted / f"Jane Doe - Scene {scene}.mp4", seconds)
                    _scene(unsorted / f"jane-doe-copy-{scene}-enhanced.mp4", seconds + 0.1)
                measured: list[str] = []

                def fingerprint(video: Path, seconds: float) -> list[str]:
                    measured.append(video.name)
                    return ONE_FINGERPRINT

                result = nonai_group.run(fingerprint=fingerprint)

                assert len(measured) == 3
                assert result.measured == 3

    def test_the_same_length_with_other_frames_is_another_video(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                unsorted = non_ai / "lagoon" / "0 unsorted"
                first = _scene(unsorted / "various - Example Studio - finale 1.mp4", 60.0)
                second = _scene(unsorted / "various - Example Studio - finale 2.mp4", 59.95)
                other = [f"{int(moment, 16) ^ ((1 << 64) - 1):016x}" for moment in ONE_FINGERPRINT]

                nonai_group.run(fingerprint=lambda video, seconds:
                                ONE_FINGERPRINT if video == first else other)

                assert _group(first) != _group(second)


class TestGroupingCannotFail(unittest.TestCase):
    def test_grouping_is_bookkeeping_that_never_fails_a_run_whatever_it_counted(self):
        counted = nonai_group.NonAiGroupResult(grouped=3, families=2, written=2, pruned=4,
                                               joined=1, measured=3)

        assert (counted.ok, counted.needs_an_eye) == (True, False)


if __name__ == "__main__":
    unittest.main()
