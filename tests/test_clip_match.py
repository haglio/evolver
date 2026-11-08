from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from app_support import video_ids

import evolver
from tasks import clip_match
from tests.temp_helpers import override_config, workspace_temp_dir
from util import scene_links, sidecar
from util.frame_hashes import SAMPLE_HEIGHT, SAMPLE_WIDTH

NORA = "Nora Quill"
JANE_AND_ADA = "Jane Doe, Ada Roe"


def _id(video: Path) -> str:
    return video_ids.id_of(sidecar.sidecar_path(video))


def _frames(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(count, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)


def _clip_record(performer: str, compilation: str = "Vol3", index: int = 5) -> dict:
    return {"compilation": compilation, "index": index, "performer": performer}


def _library(root: Path, files: tuple[tuple[str, int, dict], ...]):
    library = root / "videos"
    non_ai = library / "2D" / "non_AI"
    metadata = root / "metadata"
    for relative, size, payload in files:
        video = non_ai / relative
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"x" * size)
        card = (metadata / "2D" / "non_AI" / relative).with_suffix(".json")
        card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(json.dumps(payload), encoding="utf-8")
    return non_ai, override_config(
        VIDEO_LIBRARY_DIR=library, VIDEO_SEARCH_ROOT=library,
        NON_AI_DIR=non_ai, METADATA_DIR=metadata,
    )


def _recorded(clip: Path) -> dict:
    return sidecar.read(sidecar.sidecar_path(clip)).get("clip", {})


ONE_SCENE_TWO_CLIPS = (
    ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
    ("scenes/Nora-Quill_540-izb4ykfa_apo8_iris2.mp4", 400, {}),
    ("clips/Nora Quill - Nights of Nonsense 8.mp4", 50, {"clip": _clip_record(NORA, "Vol1", 9)}),
    ("clips/Nora Quill - Scene Three 3.mp4", 50, {"clip": _clip_record(NORA, "Vol4", 2)}),
)

TWO_SCENES_ONE_CLIP = (
    ("scenes/Petra-Vance_540-paci21ck.mp4", 1, {}),
    ("scenes/Petra Vance Beta Cut 4k 60fps.mp4", 1, {}),
    ("clips/Petra Vance - Scene Three 8.mp4", 1, {"clip": _clip_record("Petra Vance", "Vol7", 4)}),
)

TWO_CUTS_IN_ONE_FAMILY = (
    ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
    ("scenes/Nora-Quill-2_720-qq7mnbet.mp4", 100, {}),
    ("clips/Nora Quill - Brink.mp4", 60,
     {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
    ("clips/Nora Quill - Brink (2).mp4", 50,
     {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
)


def _two_cuts_sampler():
    first, second = _frames(400, seed=21), _frames(400, seed=22)

    def sampler(video, fps):
        if video.name == "Nora-Quill_540-izb4ykfa.mp4":
            return first
        if video.name == "Nora-Quill-2_720-qq7mnbet.mp4":
            return second
        if video.name == "Nora Quill - Brink.mp4":
            return first[80:120]
        return second[200:240]

    return sampler


class TestClipMatch(unittest.TestCase):
    def test_of_two_clips_naming_the_scenes_performer_only_the_one_in_its_frames_is_matched(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, ONE_SCENE_TWO_CLIPS)
            scene_frames = _frames(400, seed=1)

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    return scene_frames
                if "Nights" in video.name:
                    return scene_frames[80:120]
                return _frames(40, seed=2)

            with settings:
                result = clip_match.run(fps=8.0, sampler=sampler)

                scene = non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"
                cut_from_it = non_ai / "clips" / "Nora Quill - Nights of Nonsense 8.mp4"
                assert result.matched == 1
                assert scene_links.scene_id(_recorded(cut_from_it)) == _id(scene)
                assert _recorded(cut_from_it)["scene_offset"] == 10.0
                other = non_ai / "clips" / "Nora Quill - Scene Three 3.mp4"
                assert scene_links.SCENE_ID not in _recorded(other)

    def test_the_clips_own_record_survives_the_answer(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, ONE_SCENE_TWO_CLIPS)
            scene_frames = _frames(400, seed=1)

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    return scene_frames
                if "Nights" in video.name:
                    return scene_frames[80:120]
                return _frames(40, seed=2)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

                cut_from_it = non_ai / "clips" / "Nora Quill - Nights of Nonsense 8.mp4"
                assert _recorded(cut_from_it)["compilation"] == "Vol1"
                assert _recorded(cut_from_it)["index"] == 9

    def test_decodes_the_cheapest_version_of_a_scene(self):
        with workspace_temp_dir() as root:
            _, settings = _library(root, ONE_SCENE_TWO_CLIPS)
            sampled = []

            def sampler(video, fps):
                sampled.append(video)
                return _frames(40, seed=3)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

            assert not [v for v in sampled if "apo8" in v.name]

    def test_separates_two_scenes_whose_names_share_a_prefix(self):
        with workspace_temp_dir() as root:
            _, settings = _library(root, TWO_SCENES_ONE_CLIP)
            scenes = []

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    scenes.append(video)
                return _frames(4, seed=5)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

            assert len(scenes) == 2

    def test_the_better_alignment_takes_a_clip_two_scenes_both_hold(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_SCENES_ONE_CLIP)
            release_540 = _frames(400, seed=6)
            clip_frames = release_540[80:120]

            def sampler(video, fps):
                if video.name.startswith("Petra-Vance_540"):
                    return release_540
                if video.name.endswith("60fps.mp4"):
                    return np.concatenate([_frames(24, seed=9), clip_frames[:20]])
                return clip_frames

            with settings:
                result = clip_match.run(fps=8.0, sampler=sampler)

                scene = non_ai / "scenes" / "Petra-Vance_540-paci21ck.mp4"
                clip = non_ai / "clips" / "Petra Vance - Scene Three 8.mp4"
                assert result.matched == 1
                assert scene_links.scene_id(_recorded(clip)) == _id(scene)
                assert _recorded(clip)["scene_offset"] == 10.0

    def test_matches_a_scene_bucketed_under_a_shared_version_group(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("scenes/Jane Doe_iris2.mp4", 900, {"version": {"group": "Jane Doe"}}),
                ("scenes/Jane-Doe-&-Ada-Roe-b4t7k1qz-old_iris2.mp4", 500,
                 {"version": {"group": "Jane Doe"}}),
                ("scenes/Jane Doe - Cut to Length.mp4", 100, {"version": {"group": "Jane Doe"}}),
                ("clips/Jane Doe, Ada Roe - Load Bearing 2.mp4", 50,
                 {"clip": _clip_record(JANE_AND_ADA, "Vol3", 6)}),
            ))
            two_performers = _frames(400, seed=11)

            def sampler(video, fps):
                if video.name.startswith("Jane-Doe-&-Ada-Roe"):
                    return two_performers
                if video.parent.name == "clips":
                    return two_performers[80:120]
                return _frames(40, seed=12)

            with settings:
                result = clip_match.run(fps=8.0, sampler=sampler)

                scene = non_ai / "scenes" / "Jane-Doe-&-Ada-Roe-b4t7k1qz-old_iris2.mp4"
                clip = non_ai / "clips" / "Jane Doe, Ada Roe - Load Bearing 2.mp4"
                assert result.matched == 1
                assert scene_links.scene_id(_recorded(clip)) == _id(scene)
                assert _recorded(clip)["scene_offset"] == 10.0

    def test_a_family_holding_two_cuts_has_each_entry_measured_rather_than_told(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_CUTS_IN_ONE_FAMILY)

            with settings:
                clip_match.run(fps=8.0, sampler=_two_cuts_sampler())

                bigger = _recorded(non_ai / "clips" / "Nora Quill - Brink.mp4")
                smaller = _recorded(non_ai / "clips" / "Nora Quill - Brink (2).mp4")
                assert scene_links.scene_id(bigger) == _id(non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4")
                assert bigger["scene_offset"] == 10.0
                assert scene_links.scene_id(smaller) == _id(non_ai / "scenes" / "Nora-Quill-2_720-qq7mnbet.mp4")
                assert smaller["scene_offset"] == 25.0

    def test_a_family_entry_that_is_another_encode_still_gets_the_answer(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
                ("clips/Nora Quill - Brink.mp4", 60,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
                ("clips/Nora Quill - Brink_apo8_iris2.mp4", 50,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
            ))
            scene_frames = _frames(400, seed=23)

            def sampler(video, fps):
                return scene_frames if video.parent.name == "scenes" else scene_frames[80:120]

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

                scene = non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"
                for name in ("Nora Quill - Brink.mp4", "Nora Quill - Brink_apo8_iris2.mp4"):
                    assert scene_links.scene_id(_recorded(non_ai / "clips" / name)) == _id(scene)

    def test_a_wrong_match_an_earlier_run_wrote_is_dropped(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_CUTS_IN_ONE_FAMILY)
            stale = (root / "metadata" / "2D" / "non_AI" / "clips"
                     / "Nora Quill - Brink (2).json")
            payload = json.loads(stale.read_text(encoding="utf-8"))
            payload["clip"].update(full_video_id=video_ids.id_of(
                root / "metadata" / "2D" / "non_AI" / "scenes" / "Nora-Quill_540-izb4ykfa.json"),
                scene_offset=10.0)
            stale.write_text(json.dumps(payload), encoding="utf-8")

            with settings:
                clip_match.run(fps=8.0, sampler=_two_cuts_sampler())

                recorded = _recorded(non_ai / "clips" / "Nora Quill - Brink (2).mp4")
                assert scene_links.scene_id(recorded) == _id(non_ai / "scenes" / "Nora-Quill-2_720-qq7mnbet.mp4")
                assert recorded["compilation"] == "Vol3"

    def test_a_family_entry_in_no_scene_at_all_is_left_with_nothing(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
                ("clips/Nora Quill - Brink.mp4", 60,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
                ("clips/Nora Quill - Brink (2).mp4", 50,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
            ))
            stale = (root / "metadata" / "2D" / "non_AI" / "clips"
                     / "Nora Quill - Brink (2).json")
            payload = json.loads(stale.read_text(encoding="utf-8"))
            payload["clip"].update(full_video_id=video_ids.id_of(
                root / "metadata" / "2D" / "non_AI" / "scenes" / "Nora-Quill_540-izb4ykfa.json"),
                scene_offset=99.0)
            stale.write_text(json.dumps(payload), encoding="utf-8")
            scene_frames = _frames(400, seed=21)

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    return scene_frames
                if video.name == "Nora Quill - Brink.mp4":
                    return scene_frames[80:120]
                return _frames(40, seed=31)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

                recorded = _recorded(non_ai / "clips" / "Nora Quill - Brink (2).mp4")
                assert scene_links.SCENE_ID not in recorded
                assert "scene_offset" not in recorded
                assert recorded["compilation"] == "Vol3"

    def test_a_clip_compared_with_every_scene_of_its_performer_is_decoded_once(self):
        with workspace_temp_dir() as root:
            _, settings = _library(root, TWO_SCENES_ONE_CLIP)
            sampled = []

            def sampler(video, fps):
                sampled.append(video.name)
                return _frames(4, seed=5)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

            assert sampled.count("Petra Vance - Scene Three 8.mp4") == 1

    def test_a_clip_with_no_family_recorded_yet_is_nobodys_other_version(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
                ("clips/Nora Quill - Brink.mp4", 60, {"clip": _clip_record(NORA)}),
                ("clips/Nora Quill - Brink_apo8_iris2.mp4", 50, {"clip": _clip_record(NORA)}),
            ))
            scene = non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"
            alike_by_name = non_ai / "clips" / "Nora Quill - Brink_apo8_iris2.mp4"
            scene_frames = _frames(400, seed=21)

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    return scene_frames
                if video.name == "Nora Quill - Brink.mp4":
                    return scene_frames[80:120]
                return _frames(40, seed=31)

            with settings:
                clip_match.record(alike_by_name, scene, offset=99.0)
                clip_match.run(fps=8.0, sampler=sampler)

                assert _recorded(alike_by_name)["scene_offset"] == 99.0

    def test_a_library_with_no_clips_records_nothing(self):
        with workspace_temp_dir() as root:
            _, settings = _library(root, (("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),))
            sampled = []

            with settings:
                result = clip_match.run(fps=8.0, sampler=lambda v, fps: sampled.append(v))

            assert (result.scenes, result.clips, result.matched) == (1, 0, 0)
            assert sampled == []


class TestNotAPipelineStage(unittest.TestCase):
    def test_it_reads_every_video_end_to_end_so_it_is_run_by_hand_and_never_by_the_pipeline(self):
        assert "clip_match" not in evolver.ALL_STAGES
        assert clip_match not in vars(evolver).values()


class TestCouldBeCutFrom(unittest.TestCase):
    def test_a_scene_named_for_every_performer_and_a_hash_is_a_candidate(self):
        assert clip_match.could_be_cut_from(
            _clip_record(JANE_AND_ADA), Path("Jane-Doe-&-Ada-Roe-b4t7k1qz.mp4"),
        )

    def test_a_scene_missing_one_of_them_is_not(self):
        assert not clip_match.could_be_cut_from(
            _clip_record(JANE_AND_ADA), Path("Jane-Doe_540-izb4ykfa.mp4"),
        )

    def test_a_clip_that_names_no_performer_matches_nothing(self):
        assert not clip_match.could_be_cut_from({}, Path("Jane-Doe_540-izb4ykfa.mp4"))

    def test_a_name_spelled_with_its_letters_doubled_differently_is_the_same_name(self):
        assert clip_match.could_be_cut_from(
            _clip_record("Mira Vosss"), Path("Mira Voss - studio video original.mp4"),
        )
        assert clip_match.could_be_cut_from(
            _clip_record("Jonna Vale"), Path("Jona-Valle-&-Ada-Roe_540-b4t7k1qz.mp4"),
        )


class TestRecordAndForget(unittest.TestCase):
    def test_record_leaves_the_rest_of_the_sidecar_alone(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("clips/Nora Quill - Brink.mp4", 60,
                 {"clip": _clip_record(NORA), "video": {"action": "Alpha"},
                  "version": {"group": "Nora Quill - Brink", "processed": False}}),
            ))
            clip = non_ai / "clips" / "Nora Quill - Brink.mp4"
            scene = non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"

            with settings:
                clip_match.record(clip, scene, offset=808.25)

                payload = sidecar.read(sidecar.sidecar_path(clip))
                assert payload["clip"] == {"compilation": "Vol3", "index": 5, "performer": NORA, **scene_links.link_to(scene), "scene_offset": 808.25}
                assert payload["video"] == {"action": "Alpha"}

    def test_forget_leaves_a_match_to_another_scene_alone(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("clips/Nora Quill - Brink.mp4", 60, {"clip": _clip_record(NORA)}),
            ))
            clip = non_ai / "clips" / "Nora Quill - Brink.mp4"
            one = non_ai / "scenes" / "one.mp4"
            another = non_ai / "scenes" / "another.mp4"

            with settings:
                clip_match.record(clip, one, offset=4.0)
                clip_match.forget(clip, another)

                assert scene_links.scene_id(_recorded(clip)) == _id(one)

    def test_neither_leaves_anything_beside_the_sidecar(self):
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("clips/Nora Quill - Brink.mp4", 60, {"clip": _clip_record(NORA)}),
            ))
            clip = non_ai / "clips" / "Nora Quill - Brink.mp4"
            scene = non_ai / "scenes" / "one.mp4"

            with settings:
                clip_match.record(clip, scene, offset=4.0)
                clip_match.forget(clip, scene)

                folder = sidecar.sidecar_path(clip).parent
                assert [p.name for p in sorted(folder.iterdir())] == ["Nora Quill - Brink.json"]


if __name__ == "__main__":
    unittest.main()
