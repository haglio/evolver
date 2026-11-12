from __future__ import annotations

import unittest

from tasks import provenance_sweep
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from util import provenance, sidecar, topaz

_TOPAZS_OWN_WORDS = "Processed using apo-8 replacing duplicate frames. Enhanced using gcg-5. 4x upscale"

_MADE_HERE = provenance.reconstructed("evolver", method="non_ai_upscale")

_A_STAMP_TAKEN_WHEN_THE_UPSCALE_WAS_MADE = {
    **provenance.reconstructed("evolver", method="non_ai_upscale", method_version="v001"),
    "app_commit": "0123abc", "app_dirty": False, "stamped_at": "2026-09-01T20:15:00+00:00"}


def _noting(note: str):
    return lambda video: note


def _refuses_to_be_called(video):
    raise AssertionError(f"no note should have been read: {video}")


def _processed(lib: LaneLibrary, name: str):
    return touch_video(lib.non_ai / "alpha" / "3_good_to_go" / "processed" / f"{name}_apo8_iris2.mp4")


class TestAnAiVideo(unittest.TestCase):
    def test_no_ai_upscale_and_no_ai_genau_flick_is_given_a_sidecar_since_the_gallery_is_their_record(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")
                touch_video(lib.kino_upscales / "portrait" / "origenerator" / "wan22_i2v_00001__topaz.mp4")
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_one.mp4")
                touch_video(lib.kino_upscales / "portrait" / "examplesource" / "clip_one_topaz.mp4")
                touch_video(lib.genau_flicks / "2D" / "AI" / "loop_one_topaz.mp4")

                result = provenance_sweep.run(read_note=_refuses_to_be_called)

            assert not lib.metadata.exists()
        assert (result.from_notes, result.unknown, result.already, result.deferred) == (0, 0, 0, 0)


class TestANonAiUpscale(unittest.TestCase):
    def test_one_whose_note_is_in_the_stages_own_words_says_evolver_made_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscale = _processed(lib, "Jane-Doe-scene-1")

                provenance_sweep.run(read_note=_noting(topaz.NON_AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(upscale))

        assert recorded[provenance.BLOCK] == {provenance.UPSCALE_NON_AI: _MADE_HERE}

    def test_one_whose_note_names_no_settings_here_is_recorded_with_its_maker_unknown(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscale = _processed(lib, "scene-four")

                provenance_sweep.run(read_note=_noting(_TOPAZS_OWN_WORDS))

                recorded = sidecar.read(sidecar.sidecar_path(upscale))

        assert recorded[provenance.BLOCK] == {provenance.UPSCALE_NON_AI: provenance.reconstructed(None)}

    def test_a_stamp_taken_when_the_upscale_was_made_is_left_as_it_stands(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscale = _processed(lib, "scene-two")
                write_sidecar(sidecar.sidecar_path(upscale),
                              {provenance.BLOCK: {provenance.UPSCALE_NON_AI: _A_STAMP_TAKEN_WHEN_THE_UPSCALE_WAS_MADE}})

                provenance_sweep.run(read_note=_refuses_to_be_called)

                recorded = sidecar.read(sidecar.sidecar_path(upscale))

        assert recorded[provenance.BLOCK] == {provenance.UPSCALE_NON_AI: _A_STAMP_TAKEN_WHEN_THE_UPSCALE_WAS_MADE}

    def test_a_stamp_the_upscale_writes_while_the_sweep_reads_its_note_is_never_written_over(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscale = _processed(lib, "scene-three")
                record = sidecar.sidecar_path(upscale)

                def the_upscale_lands_while_its_note_is_read(_video):
                    write_sidecar(record, {provenance.BLOCK: {
                        provenance.UPSCALE_NON_AI: _A_STAMP_TAKEN_WHEN_THE_UPSCALE_WAS_MADE}})
                    return _TOPAZS_OWN_WORDS

                provenance_sweep.run(read_note=the_upscale_lands_while_its_note_is_read)

                recorded = sidecar.read(record)

        assert recorded[provenance.BLOCK] == {provenance.UPSCALE_NON_AI: _A_STAMP_TAKEN_WHEN_THE_UPSCALE_WAS_MADE}


class TestAGenauFlickGenaumacherCut(unittest.TestCase):
    def test_a_loop_delivered_before_records_were_kept_says_the_settings_its_note_names(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                clip = touch_video(lib.genau_flicks / "2D" / "non_AI" / "loop_one_topaz.mp4")

                provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(clip))

        assert recorded[provenance.BLOCK] == {provenance.UPSCALE: provenance.reconstructed("evolver", method="ai_upscale")}


class TestWhatARunSays(unittest.TestCase):
    def test_records_a_note_named_are_counted_apart_from_ones_nothing_named(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                for name in ("scene-six", "scene-seven"):
                    _processed(lib, name)
                notes = {"scene-six_apo8_iris2": topaz.NON_AI_UPSCALE.videoai_tag,
                         "scene-seven_apo8_iris2": _TOPAZS_OWN_WORDS}

                result = provenance_sweep.run(read_note=lambda video: notes[video.stem])

        assert (result.from_notes, result.unknown) == (1, 1)


class TestNotHoldingUpTheRun(unittest.TestCase):
    def test_a_run_reads_no_more_notes_than_its_limit_and_leaves_the_rest_for_the_next(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                for index in range(3):
                    _processed(lib, f"scene-{index}")
                read = []

                def reading(video):
                    read.append(video)
                    return topaz.NON_AI_UPSCALE.videoai_tag

                first = provenance_sweep.run(read_note=reading, notes_per_run=2)
                second = provenance_sweep.run(read_note=reading, notes_per_run=2)

        assert (first.from_notes, first.deferred) == (2, 1)
        assert (second.from_notes, second.already) == (1, 2)
        assert len(read) == 3


class TestRunningItAgain(unittest.TestCase):
    def test_a_library_already_recorded_is_left_alone_and_says_so(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                _processed(lib, "scene-three")

                provenance_sweep.run(read_note=_noting(topaz.NON_AI_UPSCALE.videoai_tag))
                again = provenance_sweep.run(read_note=_noting(topaz.NON_AI_UPSCALE.videoai_tag))

        assert (again.unknown, again.already) == (0, 1)

    def test_a_file_whose_record_is_complete_never_has_its_note_read_again(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                _processed(lib, "scene-five")

                provenance_sweep.run(read_note=_noting(topaz.NON_AI_UPSCALE.videoai_tag))
                again = provenance_sweep.run(read_note=_refuses_to_be_called)

        assert again.already == 1


if __name__ == "__main__":
    unittest.main()
