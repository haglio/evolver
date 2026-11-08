from __future__ import annotations

import unittest
from pathlib import Path

from tasks import video_kinds
from tests.temp_helpers import (
    LaneLibrary,
    a_drive_that_is_not_there,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import orientation, sidecar, video_kind

GENAU_SOURCE = "example-loop-clips"


def _probe(durations: dict[str, float]):
    return lambda video: durations.get(video.stem)


def _orientations(by_stem: dict[str, str]):
    return lambda video: by_stem.get(video.stem, orientation.UNKNOWN)


def _orientation_unknown(_video):
    return orientation.UNKNOWN


class TestAiLane(unittest.TestCase):
    def test_a_sorted_clip_is_recorded_on_the_sidecar_at_its_upscale_path(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_a_topaz.mp4"
                )
                write_sidecar(path, {"video": {"prompt": "a prompt"}})

                result = video_kinds.run(probe=_probe({video.stem: 5.0}),
                                         orientation_probe=_orientation_unknown)

                payload = sidecar.read(path)
            assert video_kind.kind_of(payload) == video_kind.CLIP
            assert payload["video"]["prompt"] == "a prompt"
            assert result.recorded == 1

    def test_an_act_struck_out_while_the_stage_measures_is_still_there_after(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_c.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_c_topaz.mp4"
                )
                write_sidecar(path, {"video": {"action": "Alpha"}})

                def measure_while_a_viewer_rejects(clip):
                    write_sidecar(path, {"video": {"wrong_action": "Alpha"}})
                    return 5.0

                video_kinds.run(probe=measure_while_a_viewer_rejects,
                                orientation_probe=_orientation_unknown)

                payload = sidecar.read(path)
            assert payload["video"]["wrong_action"] == "Alpha"
            assert "action" not in payload["video"]
            assert video_kind.kind_of(payload) == video_kind.CLIP

    def test_a_long_generated_clip_is_full_length(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.sorted_dir / "provider2" / "landscape" / "clip_b.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "landscape" / "provider2" / "clip_b_topaz.mp4"
                )

                video_kinds.run(probe=_probe({video.stem: 240.0}),
                                orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(path)) == video_kind.FULL_LENGTH

    def test_a_clip_in_the_genau_source_is_a_genau_loop_before_it_is_finished(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                touch_video(lib.sorted_dir / GENAU_SOURCE / "portrait" / "loop_1.mp4")
                path = sidecar.sidecar_path(lib.genau_flicks / "2D" / "AI" / "loop_1_topaz.mp4")

                video_kinds.run(probe=_unmeasurable, orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(path)) == video_kind.GENAU_FLICK


class TestGenauLane(unittest.TestCase):
    def test_a_delivered_loop_gets_a_record_of_its_own(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                clip = touch_video(lib.genau_flicks / "loop_2_topaz.mp4")

                result = video_kinds.run(probe=_unmeasurable,
                                         orientation_probe=_orientation_unknown)

                payload = sidecar.read(sidecar.sidecar_path(clip))
            assert video_kind.kind_of(payload) == video_kind.GENAU_FLICK
            assert result.recorded == 1
            assert (lib.metadata / "genau" / "flicks" / "loop_2_topaz.json").is_file()


class TestNonAiLane(unittest.TestCase):
    def _bucket(self, lib) -> Path:
        return lib.non_ai / "alpha"

    def test_a_scene_carved_out_of_a_longer_one_is_an_excerpt(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(self._bucket(lib) / "0 unsorted" / "Jane-Doe-scene-2.mp4")
                path = sidecar.sidecar_path(video)
                write_sidecar(path, {"clip": {"index": 2, "count": 9}})

                video_kinds.run(probe=_unmeasurable, orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(path)) == video_kind.CLIP

    def test_a_declared_clip_folder_vouches_for_clips_split_before_any_record_said_so(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE, CLIP_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                video = touch_video(self._bucket(lib) / "excerpts" / "0 unsorted" / "Ada-Roe-7.mp4")

                video_kinds.run(probe=_probe({video.stem: 900.0}),
                                orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.CLIP

    def test_an_ordinary_scene_is_full_length(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(self._bucket(lib) / "3_good_to_go" / "Jane-Doe-scene-1.mp4")

                video_kinds.run(probe=_probe({video.stem: 1800.0}),
                                orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.FULL_LENGTH


class TestRunningItAgain(unittest.TestCase):
    def test_a_record_already_complete_is_left_alone_and_never_measured(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_c.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_c_topaz.mp4"
                )
                write_sidecar(path, video_kind.oriented(video_kind.timed(
                    video_kind.stamped({}, video_kind.FULL_LENGTH), 240.0), orientation.PORTRAIT))

                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_refuses_to_be_called)

                assert video_kind.kind_of(sidecar.read(path)) == video_kind.FULL_LENGTH
            assert (result.recorded, result.already) == (0, 1)
            assert video.name == "clip_c.mp4"

    def test_a_kind_recorded_before_running_times_were_kept_is_measured_once(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_i.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_i_topaz.mp4"
                )
                write_sidecar(path, video_kind.stamped({}, video_kind.FULL_LENGTH))

                first = video_kinds.run(probe=_probe({"clip_i": 240.0}),
                                        orientation_probe=_orientation_unknown)
                again = video_kinds.run(probe=_refuses_to_be_called,
                                        orientation_probe=_refuses_to_be_called)

                assert video_kind.duration_of(sidecar.read(path)) == 240.0
            assert (first.recorded, again.already) == (1, 1)

    def test_a_second_run_writes_nothing(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_d.mp4")

                video_kinds.run(probe=_probe({video.stem: 6.0}),
                                orientation_probe=_orientation_unknown)
                again = video_kinds.run(probe=_refuses_to_be_called,
                                        orientation_probe=_refuses_to_be_called)

            assert (again.recorded, again.already) == (0, 1)


def _unmeasurable(_video):
    return None


def _refuses_to_be_called(video):
    raise AssertionError(f"nothing should have been measured: {video}")


class TestKeepingTheRunningTime(unittest.TestCase):
    def test_the_running_time_lands_beside_the_kind(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-4.mp4")

                video_kinds.run(probe=_probe({video.stem: 1800.0}),
                                orientation_probe=_orientation_unknown)

                payload = sidecar.read(sidecar.sidecar_path(video))
            assert video_kind.duration_of(payload) == 1800.0
            assert video_kind.kind_of(payload) == video_kind.FULL_LENGTH

    def test_an_excerpt_is_measured_even_though_its_kind_was_free(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-5.mp4")
                path = sidecar.sidecar_path(video)
                write_sidecar(path, {"clip": {"index": 5, "count": 9}})

                video_kinds.run(probe=_probe({video.stem: 240.0}),
                                orientation_probe=_orientation_unknown)

                payload = sidecar.read(path)
            assert video_kind.kind_of(payload) == video_kind.CLIP
            assert video_kind.duration_of(payload) == 240.0

    def test_measuring_a_free_kind_still_counts_against_the_batch_limit(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(VIDEO_KIND_PROBES_PER_RUN=1):
                for index in (1, 2):
                    touch_video(lib.genau_flicks / f"loop_{index}_topaz.mp4")
                measured = []

                video_kinds.run(probe=lambda video: measured.append(video) or 4.0,
                                orientation_probe=_orientation_unknown)

            assert len(measured) == 1

    def test_a_free_kind_still_lands_when_nothing_can_measure_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                clip = touch_video(lib.genau_flicks / "loop_4_topaz.mp4")

                result = video_kinds.run(probe=_unmeasurable,
                                         orientation_probe=_orientation_unknown)

                payload = sidecar.read(sidecar.sidecar_path(clip))
            assert video_kind.kind_of(payload) == video_kind.GENAU_FLICK
            assert video_kind.duration_of(payload) is None
            assert (result.recorded, result.skipped) == (1, 0)


class TestRecordingTheOrientation(unittest.TestCase):
    def test_a_scene_s_orientation_is_measured_and_lands_beside_its_kind(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-6.mp4")

                video_kinds.run(
                    probe=_probe({video.stem: 1800.0}),
                    orientation_probe=_orientations({video.stem: orientation.PORTRAIT}))

                payload = sidecar.read(sidecar.sidecar_path(video))
            assert video_kind.orientation_of(payload) == orientation.PORTRAIT
            assert video_kind.kind_of(payload) == video_kind.FULL_LENGTH

    def test_a_genau_flick_s_orientation_is_measured_too(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                flick = touch_video(lib.genau_flicks / "loop_5_topaz.mp4")

                video_kinds.run(
                    probe=_probe({flick.stem: 4.0}),
                    orientation_probe=_orientations({flick.stem: orientation.LANDSCAPE}))

                payload = sidecar.read(sidecar.sidecar_path(flick))
            assert video_kind.orientation_of(payload) == orientation.LANDSCAPE

    def test_a_generated_clip_s_orientation_is_the_folder_it_was_sorted_into(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.sorted_dir / "provider2" / "landscape" / "clip_j.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "landscape" / "provider2" / "clip_j_topaz.mp4"
                )

                video_kinds.run(probe=_probe({video.stem: 5.0}),
                                orientation_probe=_refuses_to_be_called)

                assert video_kind.orientation_of(sidecar.read(path)) == orientation.LANDSCAPE

    def test_a_generated_clip_s_orientation_costs_no_measurement(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE, VIDEO_KIND_PROBES_PER_RUN=0):
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_k.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_k_topaz.mp4"
                )
                write_sidecar(path, video_kind.timed(
                    video_kind.stamped({}, video_kind.CLIP), 5.0))

                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_refuses_to_be_called)

                assert video_kind.orientation_of(sidecar.read(path)) == orientation.PORTRAIT
            assert result.recorded == 1

    def test_an_orientation_is_measured_once(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-7.mp4")

                video_kinds.run(
                    probe=_probe({video.stem: 1800.0}),
                    orientation_probe=_orientations({video.stem: orientation.LANDSCAPE}))
                again = video_kinds.run(probe=_refuses_to_be_called,
                                        orientation_probe=_refuses_to_be_called)

            assert (again.recorded, again.already) == (0, 1)

    def test_a_video_whose_orientation_nothing_could_tell_waits_for_a_run_that_can(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-8.mp4")
                path = sidecar.sidecar_path(video)

                video_kinds.run(probe=_probe({video.stem: 1800.0}),
                                orientation_probe=_orientation_unknown)
                unmeasured = video_kind.orientation_of(sidecar.read(path))
                video_kinds.run(
                    probe=_refuses_to_be_called,
                    orientation_probe=_orientations({video.stem: orientation.PORTRAIT}))

                measured = video_kind.orientation_of(sidecar.read(path))
            assert (unmeasured, measured) == ("", orientation.PORTRAIT)

    def test_measuring_an_orientation_counts_against_the_batch_limit(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE, VIDEO_KIND_PROBES_PER_RUN=1):
                for index in range(3):
                    video = touch_video(lib.non_ai / "alpha" / "0 unsorted" / f"scene-{index}.mp4")
                    write_sidecar(sidecar.sidecar_path(video), video_kind.timed(
                        video_kind.stamped({}, video_kind.FULL_LENGTH), 1800.0))
                measured = []

                result = video_kinds.run(
                    probe=_refuses_to_be_called,
                    orientation_probe=lambda video: measured.append(video) or orientation.PORTRAIT)

            assert len(measured) == 1
            assert (result.recorded, result.deferred) == (1, 2)


class TestWhatItRefusesToGuess(unittest.TestCase):
    def test_a_clip_nothing_can_measure_waits_for_a_run_that_can_rather_than_record_a_guess_nothing_could_undo(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_e.mp4")
                path = sidecar.sidecar_path(
                    lib.kino_upscales / "portrait" / "provider2" / "clip_e_topaz.mp4"
                )

                result = video_kinds.run(probe=_unmeasurable,
                                         orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(path)) == ""
            assert (result.recorded, result.skipped) == (0, 1)


class TestReachingEveryVideoTheMainFunestraPlays(unittest.TestCase):
    def test_a_folder_holding_no_stage_folders_still_gets_its_kind(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                video = touch_video(lib.non_ai / "loose" / "landscape" / "clip_f_topaz.mp4")

                video_kinds.run(probe=_probe({video.stem: 4.0}),
                                orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.CLIP

    def test_a_vr_video_kept_on_the_cloud_drive_gets_its_running_time_where_the_library_files_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            vr_root = root / "cloud" / "VR"
            video = touch_video(vr_root / "finished" / "scene one.mp4")
            with lib.config(VR_VIDEO_DIR=vr_root):
                video_kinds.run(probe=_probe({video.stem: 1800.0}),
                                orientation_probe=_orientation_unknown)

            recorded = sidecar.read(lib.metadata / "VR" / "finished" / "scene one.json")
            assert video_kind.duration_of(recorded) == 1800.0

    def test_nothing_asks_whether_a_vr_video_is_portrait_or_landscape(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            vr_root = root / "cloud" / "VR"
            video = touch_video(vr_root / "finished" / "scene one.mp4")
            with lib.config(VR_VIDEO_DIR=vr_root):
                result = video_kinds.run(probe=_probe({video.stem: 1800.0}),
                                         orientation_probe=_refuses_to_be_called)

            assert result.recorded == 1

    def test_a_vr_video_whose_running_time_is_on_file_is_known_and_owes_nothing(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            vr_root = root / "cloud" / "VR"
            touch_video(vr_root / "finished" / "scene one.mp4")
            write_sidecar(lib.metadata / "VR" / "finished" / "scene one.json",
                          video_kind.timed(video_kind.stamped({}, video_kind.FULL_LENGTH), 1800.0))
            with lib.config(VR_VIDEO_DIR=vr_root):
                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_refuses_to_be_called)

            assert (result.already, result.deferred) == (1, 0)

    def test_nothing_is_asked_of_the_cloud_drive_while_it_is_not_there(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(VR_VIDEO_DIR=a_drive_that_is_not_there() / "VR"):
                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_refuses_to_be_called)

            assert result == video_kinds.VideoKindsResult()

    def test_a_run_asks_the_cloud_drive_about_only_so_many_vr_videos_while_the_headset_may_stream_from_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            vr_root = root / "cloud" / "VR"
            for index in range(5):
                touch_video(vr_root / "finished" / f"scene {index}.mp4")
            measured = []
            with lib.config(VR_VIDEO_DIR=vr_root, CLOUD_DRIVE_PROBES_PER_RUN=2):
                result = video_kinds.run(probe=lambda video: measured.append(video) or 1800.0,
                                         orientation_probe=_refuses_to_be_called)

            assert (len(measured), result.recorded, result.deferred) == (2, 2, 3)

    def test_a_vr_video_the_cloud_drive_gives_no_answer_about_ends_its_asking_for_the_run(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            vr_root = root / "cloud" / "VR"
            for index in range(3):
                touch_video(vr_root / "finished" / f"scene {index}.mp4")
            asked = []
            with lib.config(VR_VIDEO_DIR=vr_root):
                result = video_kinds.run(probe=asked.append,
                                         orientation_probe=_refuses_to_be_called)

            assert (len(asked), result.skipped, result.deferred) == (1, 1, 2)


class TestNotHoldingTheRestOfThePipelineUp(unittest.TestCase):

    def test_a_run_measures_no_more_than_the_batch_limit(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(VIDEO_KIND_PROBES_PER_RUN=2):
                for index in range(5):
                    touch_video(lib.sorted_dir / "provider2" / "portrait" / f"clip_{index}.mp4")
                measured = []

                first = video_kinds.run(probe=lambda video: measured.append(video) or 4.0,
                                        orientation_probe=_orientation_unknown)
                second = video_kinds.run(probe=lambda video: measured.append(video) or 4.0,
                                         orientation_probe=_orientation_unknown)
                third = video_kinds.run(probe=lambda video: measured.append(video) or 4.0,
                                        orientation_probe=_orientation_unknown)

            assert [first.recorded, second.recorded, third.recorded] == [2, 2, 1]
            assert len(measured) == 5

    def test_the_ones_it_did_not_reach_are_not_counted_as_known(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(VIDEO_KIND_PROBES_PER_RUN=1):
                for index in range(3):
                    touch_video(lib.sorted_dir / "provider2" / "portrait" / f"clip_{index}.mp4")

                result = video_kinds.run(probe=_probe({f"clip_{i}": 4.0 for i in range(3)}),
                                         orientation_probe=_orientation_unknown)

            assert (result.recorded, result.already, result.deferred) == (1, 0, 2)

    def test_the_free_answers_are_not_held_back_by_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(VIDEO_KIND_PROBES_PER_RUN=0):
                clip = touch_video(lib.genau_flicks / "loop_3_topaz.mp4")
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_g.mp4")

                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_refuses_to_be_called)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(clip))) == video_kind.GENAU_FLICK
            assert (result.recorded, result.deferred) == (1, 1)


class TestAnAnswerThatCostsNothingIsAskedAgain(unittest.TestCase):
    def test_a_scene_the_overlay_later_declares_an_excerpt_is_corrected(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            video = lib.non_ai / "alpha" / "excerpts" / "0 unsorted" / "Ada-Roe-7.mp4"
            with lib.config(GENAU_SOURCE):
                touch_video(video)
                video_kinds.run(probe=_probe({video.stem: 900.0}),
                                orientation_probe=_orientation_unknown)
                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.FULL_LENGTH

            with lib.config(GENAU_SOURCE, CLIP_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                result = video_kinds.run(probe=_refuses_to_be_called,
                                         orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.CLIP
            assert (result.recorded, result.already) == (1, 0)

    def test_a_scene_carved_after_it_was_recorded_is_corrected_too(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            video = lib.non_ai / "alpha" / "0 unsorted" / "Jane-Doe-scene-3.mp4"
            with lib.config(GENAU_SOURCE):
                touch_video(video)
                video_kinds.run(probe=_probe({video.stem: 900.0}),
                                orientation_probe=_orientation_unknown)

                path = sidecar.sidecar_path(video)
                write_sidecar(path, dict(sidecar.read(path), clip={"index": 3}))
                video_kinds.run(probe=_refuses_to_be_called, orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(path)) == video_kind.CLIP

    def test_a_scene_that_is_no_longer_an_excerpt_is_reclassified(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            video = lib.non_ai / "alpha" / "excerpts" / "0 unsorted" / "Ada-Roe-8.mp4"
            with lib.config(GENAU_SOURCE, CLIP_FOLDERS=("2D/non_AI/alpha/excerpts",)):
                touch_video(video)
                video_kinds.run(probe=_probe({video.stem: 900.0}),
                                orientation_probe=_orientation_unknown)

            with lib.config(GENAU_SOURCE):
                video_kinds.run(probe=_refuses_to_be_called, orientation_probe=_orientation_unknown)

                assert video_kind.kind_of(sidecar.read(sidecar.sidecar_path(video))) == video_kind.FULL_LENGTH

    def test_a_measured_kind_is_still_never_measured_twice(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                touch_video(lib.sorted_dir / "provider2" / "portrait" / "clip_h.mp4")

                video_kinds.run(probe=_probe({"clip_h": 4.0}),
                                orientation_probe=_orientation_unknown)
                again = video_kinds.run(probe=_refuses_to_be_called,
                                        orientation_probe=_refuses_to_be_called)

            assert (again.recorded, again.already) == (0, 1)


class TestFindingTheExcerptFoldersItself(unittest.TestCase):
    def _batch(self, lib, folder, name, carved=False):
        video = touch_video(lib.non_ai / "alpha" / folder / "0 unsorted" / name)
        if carved:
            with lib.config(GENAU_SOURCE):
                write_sidecar(sidecar.sidecar_path(video), {"clip": {"index": 1}})
        return video

    def test_a_folder_holding_the_batchs_carved_scenes_takes_the_rest_with_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                carved = [self._batch(lib, "cuts", f"carved-{i}.mp4", carved=True) for i in range(2)]
                unrecorded = self._batch(lib, "cuts", "carved-3.mp4")
                wholes = [self._batch(lib, "wholes", f"whole-{i}.mp4") for i in range(3)]

                video_kinds.run(probe=_probe({v.stem: 900.0 for v in [*carved, unrecorded, *wholes]}),
                                orientation_probe=_orientation_unknown)

                kinds = {
                    v.name: video_kind.kind_of(sidecar.read(sidecar.sidecar_path(v)))
                    for v in [*carved, unrecorded, *wholes]
                }
            assert kinds["carved-3.mp4"] == video_kind.CLIP
            assert kinds["whole-0.mp4"] == video_kind.FULL_LENGTH

    def test_one_carved_scene_stranded_among_the_wholes_does_not_undo_the_batch_s_cut_folder(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                carved = [self._batch(lib, "cuts", f"carved-{i}.mp4", carved=True) for i in range(3)]
                straggler = self._batch(lib, "wholes", "carved-moved.mp4", carved=True)
                unrecorded = self._batch(lib, "cuts", "carved-4.mp4")
                wholes = [self._batch(lib, "wholes", f"whole-{i}.mp4") for i in range(3)]
                every = [*carved, straggler, unrecorded, *wholes]

                video_kinds.run(probe=_probe({v.stem: 900.0 for v in every}),
                                orientation_probe=_orientation_unknown)

                kinds = {v.name: video_kind.kind_of(sidecar.read(sidecar.sidecar_path(v))) for v in every}
            assert kinds["carved-4.mp4"] == video_kind.CLIP
            assert kinds["whole-0.mp4"] == video_kind.FULL_LENGTH

    def test_a_batch_that_never_separated_its_cuts_keeps_every_whole_video(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                carved = self._batch(lib, "batch", "carved-1.mp4", carved=True)
                wholes = [self._batch(lib, "batch", f"whole-{i}.mp4") for i in range(3)]

                video_kinds.run(probe=_probe({v.stem: 900.0 for v in [carved, *wholes]}),
                                orientation_probe=_orientation_unknown)

                kinds = {
                    v.name: video_kind.kind_of(sidecar.read(sidecar.sidecar_path(v)))
                    for v in [carved, *wholes]
                }
            assert kinds["carved-1.mp4"] == video_kind.CLIP
            assert [kinds[f"whole-{i}.mp4"] for i in range(3)] == [video_kind.FULL_LENGTH] * 3

    def test_a_scene_carved_and_filed_beside_its_source_leaves_the_source_whole(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(GENAU_SOURCE):
                batch = lib.non_ai / "alpha"
                wholes = [touch_video(batch / "0 unsorted" / f"whole-{i}.mp4") for i in range(3)]
                source = touch_video(batch / "3_good_to_go" / "processed" / "scene.mp4")
                carved = touch_video(batch / "3_good_to_go" / "processed" / "scene-portrait.mp4")
                write_sidecar(sidecar.sidecar_path(carved), {"clip": {"full_video": str(source)}})

                video_kinds.run(probe=_probe({v.stem: 900.0 for v in [*wholes, source, carved]}),
                                orientation_probe=_orientation_unknown)

                kind = video_kind.kind_of(sidecar.read(sidecar.sidecar_path(source)))
            assert kind == video_kind.FULL_LENGTH
