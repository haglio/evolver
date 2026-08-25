"""The stage that records what kind every library video is."""

import unittest
from pathlib import Path

from tasks import video_types
from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar, video_type

# Fabricated: the real folder name is library vocabulary and lives in the
# overlay, so a test names its own and overrides the config with it.
GENAU_SOURCE = "example-loop-clips"


class _Library:
    """The folders one test's library spans, wired into config together."""

    def __init__(self, root: Path):
        videos = root / "videos"
        self.library = videos / "videos"
        self.ai = self.library / "2D" / "AI"
        self.sorted_dir = self.ai / "1_sorted"
        self.outbox = self.ai / "2_outbox" / "upscaled_by_orientation"
        self.non_ai = self.library / "2D" / "non_AI"
        self.genau_clips = videos / "genau" / "clips"
        self.metadata = videos / "metadata"
        self.search_root = videos

    def config(self, **extra):
        # Every setting the stage reads, so a test says what its library is and
        # nothing leaks in from the overlay the checkout happens to carry.
        settings = {
            "VIDEO_LIBRARY_DIR": self.library, "VIDEO_SEARCH_ROOT": self.search_root,
            "METADATA_DIR": self.metadata, "SORTED_DIR": self.sorted_dir,
            "OUT_UPSCALED_DIR": self.outbox, "NON_AI_DIR": self.non_ai,
            "GENAU_CLIPS_DIR": self.genau_clips, "GENAU_SOURCE": GENAU_SOURCE,
            "EXCERPT_FOLDERS": (),
        }
        settings.update(extra)
        return override_config(**settings)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def _probe(durations: dict[str, float]):
    """A stand-in ffprobe answering by stem, so a test says what it means."""
    return lambda video: durations.get(video.stem)


class TestAiLane(unittest.TestCase):
    def test_a_sorted_clip_is_recorded_on_the_sidecar_at_its_upscale_path(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
                path = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "provider2" / "clip_a_topaz.mp4"
                )
                sidecar.write(path, {"video": {"prompt": "a prompt"}})

                result = video_types.run(probe=_probe({video.stem: 5.0}))

                payload = sidecar.read(path)
            self.assertEqual(video_type.type_of(payload), video_type.SHORT)
            self.assertEqual(payload["video"]["prompt"], "a prompt")
            self.assertEqual(result.recorded, 1)

    def test_a_long_generated_clip_is_full_length(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(lib.sorted_dir / "provider2" / "landscape" / "clip_b.mp4")
                path = sidecar.sidecar_path(
                    lib.outbox / "landscape" / "provider2" / "clip_b_topaz.mp4"
                )

                video_types.run(probe=_probe({video.stem: 240.0}))

                self.assertEqual(
                    video_type.type_of(sidecar.read(path)), video_type.FULL_LENGTH
                )

    def test_a_clip_in_the_genau_source_is_a_genau_loop_before_it_is_delivered(self):
        """It is bound for Genau's folder, and nothing measures it on the way."""
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                _touch(lib.sorted_dir / GENAU_SOURCE / "portrait" / "loop_1.mp4")
                path = sidecar.sidecar_path(
                    lib.outbox / "portrait" / GENAU_SOURCE / "loop_1_topaz.mp4"
                )

                video_types.run(probe=_unmeasurable)

                self.assertEqual(
                    video_type.type_of(sidecar.read(path)), video_type.GENAU_CLIP
                )


class TestGenauLane(unittest.TestCase):
    def test_a_delivered_loop_gets_a_record_of_its_own(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                clip = _touch(lib.genau_clips / "loop_2_topaz.mp4")

                result = video_types.run(probe=_unmeasurable)

                payload = sidecar.read(sidecar.sidecar_path(clip))
            self.assertEqual(video_type.type_of(payload), video_type.GENAU_CLIP)
            self.assertEqual(result.recorded, 1)


class TestNonAiLane(unittest.TestCase):
    def _bucket(self, lib) -> Path:
        return lib.non_ai / "alpha"

    def test_a_scene_carved_out_of_a_longer_one_is_an_excerpt(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(self._bucket(lib) / "0 unsorted" / "Jane-Doe-scene-2.mp4")
                path = sidecar.sidecar_path(video)
                sidecar.write(path, {"clip": {"index": 2, "count": 9}})

                video_types.run(probe=_unmeasurable)

                self.assertEqual(
                    video_type.type_of(sidecar.read(path)), video_type.EXCERPT
                )

    def test_a_folder_the_overlay_declares_holds_excerpts_needs_no_record(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config(EXCERPT_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                video = _touch(self._bucket(lib) / "excerpts" / "0 unsorted" / "Ada-Roe-7.mp4")

                video_types.run(probe=_probe({video.stem: 900.0}))

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.EXCERPT,
                )

    def test_an_ordinary_scene_is_full_length(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(self._bucket(lib) / "3_good_to_go" / "Jane-Doe-scene-1.mp4")

                video_types.run(probe=_probe({video.stem: 1800.0}))

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.FULL_LENGTH,
                )


class TestRunningItAgain(unittest.TestCase):
    def test_a_kind_already_on_file_is_left_alone_and_never_measured(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_c.mp4")
                path = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "provider2" / "clip_c_topaz.mp4"
                )
                sidecar.write(path, video_type.stamped({}, video_type.FULL_LENGTH))

                result = video_types.run(probe=_refuses_to_be_called)

                self.assertEqual(
                    video_type.type_of(sidecar.read(path)), video_type.FULL_LENGTH
                )
            self.assertEqual((result.recorded, result.already), (0, 1))
            self.assertEqual(video.name, "clip_c.mp4")

    def test_a_second_run_writes_nothing(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                video = _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_d.mp4")

                video_types.run(probe=_probe({video.stem: 6.0}))
                again = video_types.run(probe=_refuses_to_be_called)

            self.assertEqual((again.recorded, again.already), (0, 1))


def _unmeasurable(_video):
    return None


def _refuses_to_be_called(video):
    raise AssertionError(f"nothing should have been measured: {video}")


class TestWhatItRefusesToGuess(unittest.TestCase):
    def test_a_clip_nothing_can_measure_waits_for_a_run_that_can(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_e.mp4")
                path = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "provider2" / "clip_e_topaz.mp4"
                )

                result = video_types.run(probe=_unmeasurable)

                self.assertEqual(video_type.type_of(sidecar.read(path)), "")
            self.assertEqual((result.recorded, result.skipped), (0, 1))


class TestReachingEveryVideoNauPlays(unittest.TestCase):
    def test_a_bucket_the_non_ai_stages_skip_still_gets_its_kind(self):
        """The exclusion keeps pipeline-output videos out of the grouping and
        the encoder, but Nau plays them, so they are asked what they are too."""
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config(NONAI_EXCLUDED_BUCKETS={"parked_ai"}):
                video = _touch(lib.non_ai / "parked_ai" / "landscape" / "clip_f_topaz.mp4")

                video_types.run(probe=_probe({video.stem: 4.0}))

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.SHORT,
                )


class TestNotHoldingTheRestOfThePipelineUp(unittest.TestCase):
    """A run measures only so many videos; the library converges over several.

    The first run over a library that has never been asked is one ffprobe per
    video, and the pipeline it runs inside has a wall clock.
    """

    def test_a_run_measures_no_more_than_the_batch_limit(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config(VIDEO_TYPE_BATCH_LIMIT=2):
                for index in range(5):
                    _touch(lib.sorted_dir / "provider2" / "portrait" / f"clip_{index}.mp4")
                measured = []

                first = video_types.run(probe=lambda video: measured.append(video) or 4.0)
                second = video_types.run(probe=lambda video: measured.append(video) or 4.0)
                third = video_types.run(probe=lambda video: measured.append(video) or 4.0)

            self.assertEqual([first.recorded, second.recorded, third.recorded], [2, 2, 1])
            self.assertEqual(len(measured), 5)

    def test_the_ones_it_did_not_reach_are_not_counted_as_known(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config(VIDEO_TYPE_BATCH_LIMIT=1):
                for index in range(3):
                    _touch(lib.sorted_dir / "provider2" / "portrait" / f"clip_{index}.mp4")

                result = video_types.run(probe=_probe({f"clip_{i}": 4.0 for i in range(3)}))

            self.assertEqual((result.recorded, result.already, result.deferred), (1, 0, 2))

    def test_the_free_answers_are_not_held_back_by_it(self):
        """Only measuring costs anything, so only measuring is counted."""
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config(VIDEO_TYPE_BATCH_LIMIT=0):
                clip = _touch(lib.genau_clips / "loop_3_topaz.mp4")
                _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_g.mp4")

                result = video_types.run(probe=_refuses_to_be_called)

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(clip))),
                    video_type.GENAU_CLIP,
                )
            self.assertEqual((result.recorded, result.deferred), (1, 1))


class TestAnAnswerThatCostsNothingIsAskedAgain(unittest.TestCase):
    """The two kinds a folder settles are re-derived every run.

    They cost nothing to reach, so a library recorded before its excerpt
    folders were declared corrects itself on the next run rather than keeping
    an answer nobody can see is wrong.
    """

    def test_a_scene_the_overlay_later_declares_an_excerpt_is_corrected(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            video = lib.non_ai / "alpha" / "excerpts" / "0 unsorted" / "Ada-Roe-7.mp4"
            with lib.config():
                _touch(video)
                video_types.run(probe=_probe({video.stem: 900.0}))
                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.FULL_LENGTH,
                )

            with lib.config(EXCERPT_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                result = video_types.run(probe=_refuses_to_be_called)

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.EXCERPT,
                )
            self.assertEqual((result.recorded, result.already), (1, 0))

    def test_a_scene_carved_after_it_was_recorded_is_corrected_too(self):
        """The `clip` record arrives when something splits the video, which is
        long after this stage first saw it."""
        with workspace_temp_dir() as root:
            lib = _Library(root)
            video = lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-3.mp4"
            with lib.config():
                _touch(video)
                video_types.run(probe=_probe({video.stem: 900.0}))

                path = sidecar.sidecar_path(video)
                sidecar.write(path, dict(sidecar.read(path), clip={"index": 3}))
                video_types.run(probe=_refuses_to_be_called)

                self.assertEqual(video_type.type_of(sidecar.read(path)), video_type.EXCERPT)

    def test_a_scene_that_is_no_longer_an_excerpt_is_measured_again(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            video = lib.non_ai / "alpha" / "excerpts" / "0 unsorted" / "Ada-Roe-8.mp4"
            with lib.config(EXCERPT_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                _touch(video)
                video_types.run(probe=_refuses_to_be_called)

            with lib.config():
                video_types.run(probe=_probe({video.stem: 900.0}))

                self.assertEqual(
                    video_type.type_of(sidecar.read(sidecar.sidecar_path(video))),
                    video_type.FULL_LENGTH,
                )

    def test_a_measured_kind_is_still_never_measured_twice(self):
        with workspace_temp_dir() as root:
            lib = _Library(root)
            with lib.config():
                _touch(lib.sorted_dir / "provider2" / "portrait" / "clip_h.mp4")

                video_types.run(probe=_probe({"clip_h": 4.0}))
                again = video_types.run(probe=_refuses_to_be_called)

            self.assertEqual((again.recorded, again.already), (0, 1))
