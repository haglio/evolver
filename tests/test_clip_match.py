"""The batch that tells each carved clip which library scene it came out of."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from tasks import clip_match
from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar
from util.frame_hashes import SAMPLE_HEIGHT, SAMPLE_WIDTH

# Every name below is invented, per this repo's fixture rule.
NORA = "Nora Quill"
JANE_AND_ADA = "Jane Doe, Ada Roe"


def _frames(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(count, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)


def _clip_record(performer: str, compilation: str = "Vol3", index: int = 5) -> dict:
    return {"compilation": compilation, "index": index, "performer": performer}


def _library(root: Path, files: tuple[tuple[str, int, dict], ...]):
    """*files* -- (path under the non-AI library, size, sidecar) -- written out.

    Returns the non-AI root and the config override that points the app at the
    tree, its mirrored metadata beside it.
    """
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

# Two different cuts saved as "X" and "X (2)". Evolver reads a version family
# off the name, so the two land in one -- but they are different footage, cut
# from two different scenes of the same performer.
TWO_CUTS_IN_ONE_FAMILY = (
    ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
    ("scenes/Nora-Quill-2_720-qq7mnbet.mp4", 100, {}),
    ("clips/Nora Quill - Brink.mp4", 60,
     {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
    ("clips/Nora Quill - Brink (2).mp4", 50,
     {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
)


def _two_cuts_sampler():
    """A sampler putting each of the two cuts in a scene of its own."""
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
    def test_records_the_scene_each_clip_was_cut_from(self):
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
                self.assertEqual(result.matched, 1)
                self.assertEqual(_recorded(cut_from_it)["full_video"], str(scene))
                self.assertEqual(_recorded(cut_from_it)["scene_offset"], 10.0)
                other = non_ai / "clips" / "Nora Quill - Scene Three 3.mp4"
                self.assertNotIn("full_video", _recorded(other))

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
                self.assertEqual(_recorded(cut_from_it)["compilation"], "Vol1")
                self.assertEqual(_recorded(cut_from_it)["index"], 9)

    def test_decodes_the_cheapest_version_of_a_scene(self):
        """Upscales cost minutes where the original costs seconds, and they hold
        the same pictures, so only the smallest file of a family is ever read."""
        with workspace_temp_dir() as root:
            _, settings = _library(root, ONE_SCENE_TWO_CLIPS)
            sampled = []

            def sampler(video, fps):
                sampled.append(video)
                return _frames(40, seed=3)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

            self.assertFalse([v for v in sampled if "apo8" in v.name])

    def test_separates_two_scenes_whose_names_share_a_prefix(self):
        """Two scenes of one performer can share a name prefix without being the
        same video. Folding them would decode one and leave the other
        unmatchable, so a cut is only another's version when the whole reduced
        title agrees, not its start."""
        with workspace_temp_dir() as root:
            _, settings = _library(root, TWO_SCENES_ONE_CLIP)
            scenes = []

            def sampler(video, fps):
                if video.parent.name == "scenes":
                    scenes.append(video)
                return _frames(4, seed=5)

            with settings:
                clip_match.run(fps=8.0, sampler=sampler)

            self.assertEqual(len(scenes), 2)

    def test_the_better_alignment_takes_a_clip_two_scenes_both_hold(self):
        """The library keeps a 540p release and a 4k re-release of one scene, cut
        to different lengths, and the clip is genuinely inside both. Only one can
        be its full_video, so the closer alignment gets it rather than whichever
        scene the sweep reached last."""
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_SCENES_ONE_CLIP)
            release_540 = _frames(400, seed=6)
            clip_frames = release_540[80:120]

            def sampler(video, fps):
                if video.name.startswith("Petra-Vance_540"):
                    return release_540
                if video.name.endswith("60fps.mp4"):  # the same scene, trimmed
                    return np.concatenate([_frames(24, seed=9), clip_frames[:20]])
                return clip_frames

            with settings:
                result = clip_match.run(fps=8.0, sampler=sampler)

                scene = non_ai / "scenes" / "Petra-Vance_540-paci21ck.mp4"
                clip = non_ai / "clips" / "Petra Vance - Scene Three 8.mp4"
                self.assertEqual(result.matched, 1)
                self.assertEqual(_recorded(clip)["full_video"], str(scene))
                self.assertEqual(_recorded(clip)["scene_offset"], 10.0)

    def test_matches_a_scene_bucketed_under_a_shared_version_group(self):
        """A version group is not always one video -- it buckets by a title read
        out of the name, so unrelated scenes of a performer land in one group.
        Read as a family, the biggest entry's name is what the candidates are
        gated on and the smallest entry's frames are what gets searched, which
        leaves the clip of every other scene in the bucket unmatchable however
        exactly its frames align."""
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
                self.assertEqual(result.matched, 1)
                self.assertEqual(_recorded(clip)["full_video"], str(scene))
                self.assertEqual(_recorded(clip)["scene_offset"], 10.0)

    def test_a_family_entry_is_measured_rather_than_told(self):
        """The winner's answer used to go to every entry of its family. Where a
        family is two different cuts, that filed one under a scene it is not in
        -- and handed that scene the wrong cut's funscript."""
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_CUTS_IN_ONE_FAMILY)

            with settings:
                clip_match.run(fps=8.0, sampler=_two_cuts_sampler())

                bigger = _recorded(non_ai / "clips" / "Nora Quill - Brink.mp4")
                smaller = _recorded(non_ai / "clips" / "Nora Quill - Brink (2).mp4")
                self.assertEqual(bigger["full_video"],
                                 str(non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"))
                self.assertEqual(bigger["scene_offset"], 10.0)
                self.assertEqual(smaller["full_video"],
                                 str(non_ai / "scenes" / "Nora-Quill-2_720-qq7mnbet.mp4"))
                self.assertEqual(smaller["scene_offset"], 25.0)

    def test_a_family_entry_that_is_another_encode_still_gets_the_answer(self):
        """The family is worth having: a genuine re-encode holds the same
        pictures, aligns in the same scene, and is recorded without being
        decoded twice for the search."""
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
                    self.assertEqual(_recorded(non_ai / "clips" / name)["full_video"], str(scene))

    def test_a_wrong_match_an_earlier_run_wrote_is_dropped(self):
        """Self-healing: the sidecars already carry answers handed out on trust,
        and an entry proved not to be in that scene must lose the one it has
        rather than keep pointing at it."""
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, TWO_CUTS_IN_ONE_FAMILY)
            stale = (root / "metadata" / "2D" / "non_AI" / "clips"
                     / "Nora Quill - Brink (2).json")
            payload = json.loads(stale.read_text(encoding="utf-8"))
            payload["clip"].update(
                full_video=str(non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"),
                scene_offset=10.0,
            )
            stale.write_text(json.dumps(payload), encoding="utf-8")

            with settings:
                clip_match.run(fps=8.0, sampler=_two_cuts_sampler())

                recorded = _recorded(non_ai / "clips" / "Nora Quill - Brink (2).mp4")
                self.assertEqual(recorded["full_video"],
                                 str(non_ai / "scenes" / "Nora-Quill-2_720-qq7mnbet.mp4"))
                self.assertEqual(recorded["compilation"], "Vol3")

    def test_a_family_entry_in_no_scene_at_all_is_left_with_nothing(self):
        """The other half of measuring rather than telling: an entry that aligns
        nowhere keeps no answer, not even the one an earlier run handed it."""
        with workspace_temp_dir() as root:
            non_ai, settings = _library(root, (
                ("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),
                ("clips/Nora Quill - Brink.mp4", 60,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
                ("clips/Nora Quill - Brink (2).mp4", 50,
                 {"clip": _clip_record(NORA), "version": {"group": "Nora Quill - Brink"}}),
            ))
            scene = non_ai / "scenes" / "Nora-Quill_540-izb4ykfa.mp4"
            stale = (root / "metadata" / "2D" / "non_AI" / "clips"
                     / "Nora Quill - Brink (2).json")
            payload = json.loads(stale.read_text(encoding="utf-8"))
            payload["clip"].update(full_video=str(scene), scene_offset=99.0)
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
                self.assertNotIn("full_video", recorded)
                self.assertNotIn("scene_offset", recorded)
                self.assertEqual(recorded["compilation"], "Vol3")

    def test_a_library_with_no_clips_records_nothing(self):
        with workspace_temp_dir() as root:
            _, settings = _library(root, (("scenes/Nora-Quill_540-izb4ykfa.mp4", 100, {}),))
            sampled = []

            with settings:
                result = clip_match.run(fps=8.0, sampler=lambda v, fps: sampled.append(v))

            self.assertEqual((result.scenes, result.clips, result.matched), (1, 0, 0))
            self.assertEqual(sampled, [])


class TestCouldBeCutFrom(unittest.TestCase):
    def test_a_scene_naming_every_performer_is_a_candidate(self):
        assert clip_match.could_be_cut_from(
            _clip_record(JANE_AND_ADA), Path("Jane-Doe-&-Ada-Roe-b4t7k1qz.mp4"),
        )

    def test_a_scene_missing_one_of_them_is_not(self):
        assert not clip_match.could_be_cut_from(
            _clip_record(JANE_AND_ADA), Path("Jane-Doe_540-izb4ykfa.mp4"),
        )

    def test_a_clip_that_names_no_performer_matches_nothing(self):
        assert not clip_match.could_be_cut_from({}, Path("Jane-Doe_540-izb4ykfa.mp4"))


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
                self.assertEqual(payload["clip"], {
                    "compilation": "Vol3", "index": 5, "performer": NORA,
                    "full_video": str(scene), "scene_offset": 808.25,
                })
                self.assertEqual(payload["video"], {"action": "Alpha"})

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

                self.assertEqual(_recorded(clip)["full_video"], str(one))

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
                self.assertEqual([p.name for p in sorted(folder.iterdir())],
                                 ["Nora Quill - Brink.json"])


if __name__ == "__main__":
    unittest.main()
