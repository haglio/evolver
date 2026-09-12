"""The stage that records what made a library video wherever nothing did at the time."""
from __future__ import annotations

import unittest

from tasks import provenance_sweep
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from tests.test_origenerator_metadata import _make_db, _row
from util import provenance, sidecar, topaz

# How the Topaz GUI describes an export made by hand, in its own words.
_TOPAZS_OWN_WORDS = "Processed using apo-8 replacing duplicate frames. Enhanced using gcg-5. 4x upscale"


def _noting(note: str):
    """A stand-in for reading the note Topaz wrote into a file: *note*, for every file."""
    return lambda video: note


def _refuses_to_be_called(video):
    raise AssertionError(f"no note should have been read: {video}")


class TestAnOrigeneratorClip(unittest.TestCase):
    def test_what_made_it_is_looked_up_in_origenerators_gallery(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")

                provenance_sweep.run(read_note=_refuses_to_be_called)

                recorded = sidecar.read(sidecar.sidecar_path(
                    lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00001__topaz.mp4"))

        self.assertEqual(recorded[provenance.BLOCK], {
            provenance.GENERATION: provenance.reconstructed(
                "origenerator", recipe="wan22_i2v", recipe_version="v007"),
        })

    def test_one_its_gallery_has_no_record_of_is_recorded_as_generated_there_and_no_more(self):
        """The row can have been deleted since. The clip came in through
        Origenerator's folder, so Origenerator made it; with which workflow, at
        which version, nothing can say any more."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["another_output_00009_.mp4"])])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "landscape" / "wan22_i2v_00002_.mp4")

                provenance_sweep.run(read_note=_refuses_to_be_called)

                recorded = sidecar.read(sidecar.sidecar_path(
                    lib.outbox / "landscape" / "origenerator" / "wan22_i2v_00002__topaz.mp4"))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.GENERATION: provenance.reconstructed("origenerator")})

    def test_a_gallery_it_cannot_read_leaves_the_generation_for_a_run_that_can(self):
        """What made the clip is still knowable -- the gallery has moved, or is
        locked for a moment -- so nothing is written in place of it, and the
        rest of the record still lands."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "moved-away.db"):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00003_.mp4")
                upscaled = touch_video(
                    lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00003__topaz.mp4")

                result = provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(set(recorded[provenance.BLOCK]), {provenance.UPSCALE})
        self.assertEqual(result.deferred, 1)

    def test_a_clip_already_recorded_never_opens_the_gallery(self):
        """The stage runs every tick and almost every clip is recorded already;
        reading the whole gallery each time, beside a running Origenerator, to
        learn nothing would be the stage's whole cost."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "moved-away.db"):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00004_.mp4")
                write_sidecar(
                    sidecar.sidecar_path(lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00004__topaz.mp4"),
                    {provenance.BLOCK: {provenance.GENERATION: provenance.reconstructed("origenerator")}})

                result = provenance_sweep.run(read_note=_refuses_to_be_called)

        self.assertEqual((result.deferred, result.already), (0, 1))


class TestAnAiUpscale(unittest.TestCase):
    def test_one_made_before_upscales_kept_a_record_says_the_recipe_its_note_names(self):
        """Topaz wrote a note into the file naming the models it used. When that
        is one of Evolver's recipes, Evolver made it with that recipe; which
        version of the recipe, and under which commit, went unrecorded."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_one.mp4")
                upscaled = touch_video(lib.outbox / "portrait" / "examplesource" / "clip_one_topaz.mp4")

                provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.UPSCALE: provenance.reconstructed("evolver", recipe="ai_upscale")})

    def test_one_whose_note_names_no_recipe_here_is_recorded_with_its_maker_unknown(self):
        """A hand export from the Topaz GUI can sit in the outbox under an
        upscale's name; its note is in Topaz's own words, and nothing says who
        made it."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_four.mp4")
                upscaled = touch_video(lib.outbox / "portrait" / "examplesource" / "clip_four_topaz.mp4")

                provenance_sweep.run(read_note=_noting(_TOPAZS_OWN_WORDS))

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.UPSCALE: provenance.reconstructed(None)})

    def test_a_stamp_taken_when_the_upscale_was_made_is_left_as_it_stands(self):
        """The stage that made the file knew the recipe, its version and the
        commit; a guess written over that would be the wrong record the stamp
        exists to prevent."""
        taken_at_the_time = {**provenance.reconstructed("evolver", recipe="ai_upscale",
                                                        recipe_version="v001"),
                             "app_commit": "0123abc", "app_dirty": False,
                             "stamped_at": "2026-09-01T20:15:00+00:00"}
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_two.mp4")
                upscaled = touch_video(lib.outbox / "portrait" / "examplesource" / "clip_two_topaz.mp4")
                write_sidecar(sidecar.sidecar_path(upscaled),
                              {provenance.BLOCK: {provenance.UPSCALE: taken_at_the_time}})

                provenance_sweep.run(read_note=_refuses_to_be_called)

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(recorded[provenance.BLOCK], {provenance.UPSCALE: taken_at_the_time})


class TestAGenauClip(unittest.TestCase):
    def test_a_loop_delivered_before_records_were_kept_says_the_recipe_its_note_names(self):
        """Delivery carries a record that was already there; a loop delivered
        before anything kept one arrives with none, and its note still says how
        it was upscaled."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                clip = touch_video(lib.genau_clips / "loop_one_topaz.mp4")

                provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(clip))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.UPSCALE: provenance.reconstructed("evolver", recipe="ai_upscale")})


class TestANonAiUpscale(unittest.TestCase):
    def test_one_whose_note_is_in_the_stages_own_words_says_evolver_made_it(self):
        """The same apo-8 and iris-2 export was made by hand in the Topaz GUI long
        before the stage existed, under the same name; only the note tells the
        two apart, Topaz's own wording on one and the stage's on the other."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                upscale = touch_video(
                    lib.non_ai / "alpha" / "3_good_to_go" / "processed" / "Jane-Doe-scene-1_apo8_iris2.mp4")

                provenance_sweep.run(read_note=_noting(topaz.NON_AI_UPSCALE.videoai_tag))

                recorded = sidecar.read(sidecar.sidecar_path(upscale))

        self.assertEqual(recorded[provenance.BLOCK], {
            provenance.UPSCALE_NON_AI: provenance.reconstructed("evolver", recipe="non_ai_upscale"),
        })


class TestWhatARunSays(unittest.TestCase):
    def test_records_a_note_named_are_counted_apart_from_ones_nothing_named(self):
        """Most upscales name their recipe in their note; the run detail has to
        show those apart from the few whose maker nobody can say."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                for name in ("clip_six", "clip_seven"):
                    touch_video(lib.sorted_dir / "examplesource" / "portrait" / f"{name}.mp4")
                    touch_video(lib.outbox / "portrait" / "examplesource" / f"{name}_topaz.mp4")
                notes = {"clip_six_topaz": topaz.AI_UPSCALE.videoai_tag,
                         "clip_seven_topaz": _TOPAZS_OWN_WORDS}

                result = provenance_sweep.run(read_note=lambda video: notes[video.stem])

        self.assertEqual((result.from_notes, result.unknown), (1, 1))


class TestNotHoldingUpTheRun(unittest.TestCase):
    def test_a_run_reads_no_more_notes_than_its_limit_and_leaves_the_rest_for_the_next(self):
        """Reading a note spawns a process per file, and the first pass over a
        library is a couple of thousand of them inside a pipeline with a clock."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                for index in range(3):
                    touch_video(lib.sorted_dir / "examplesource" / "portrait" / f"clip_{index}.mp4")
                    touch_video(lib.outbox / "portrait" / "examplesource" / f"clip_{index}_topaz.mp4")
                read = []

                def reading(video):
                    read.append(video)
                    return topaz.AI_UPSCALE.videoai_tag

                first = provenance_sweep.run(read_note=reading, notes_per_run=2)
                second = provenance_sweep.run(read_note=reading, notes_per_run=2)

        self.assertEqual((first.from_notes, first.deferred), (2, 1))
        self.assertEqual((second.from_notes, second.already), (1, 2))
        self.assertEqual(len(read), 3)


class TestRunningItAgain(unittest.TestCase):
    def test_a_library_already_recorded_is_left_alone_and_says_so(self):
        """It runs every tick, so almost every run finds nothing to do, and the
        run detail has to be able to tell that apart from a run that wrote."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_three.mp4")
                touch_video(lib.outbox / "portrait" / "examplesource" / "clip_three_topaz.mp4")

                provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))
                again = provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))

        self.assertEqual((again.unknown, again.already), (0, 1))

    def test_a_file_whose_record_is_complete_never_has_its_note_read_again(self):
        """Reading a note spawns a process per file, and a file does not change
        what made it."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_five.mp4")
                touch_video(lib.outbox / "portrait" / "examplesource" / "clip_five_topaz.mp4")

                provenance_sweep.run(read_note=_noting(topaz.AI_UPSCALE.videoai_tag))
                again = provenance_sweep.run(read_note=_refuses_to_be_called)

        self.assertEqual(again.already, 1)


if __name__ == "__main__":
    unittest.main()
