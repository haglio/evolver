"""The stage that records what made a library video wherever nothing did at the time."""
from __future__ import annotations

import unittest

from tasks import provenance_sweep
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from tests.test_origenerator_metadata import _make_db, _row
from util import provenance, sidecar


class TestAnOrigeneratorClip(unittest.TestCase):
    def test_what_made_it_is_looked_up_in_origenerators_gallery(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")

                provenance_sweep.run()

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

                provenance_sweep.run()

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

                result = provenance_sweep.run()

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

                result = provenance_sweep.run()

        self.assertEqual((result.deferred, result.already), (0, 1))


class TestAnAiUpscale(unittest.TestCase):
    def test_one_made_before_upscales_kept_a_record_is_recorded_as_evolvers_and_no_more(self):
        """The outbox and its `_topaz` names are the upscale stage's own, so
        Evolver made it. Which recipe, at which version, under which commit went
        unrecorded: the recipe choice itself has changed since."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_one.mp4")
                upscaled = touch_video(lib.outbox / "portrait" / "examplesource" / "clip_one_topaz.mp4")

                provenance_sweep.run()

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.UPSCALE: provenance.reconstructed("evolver")})

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

                provenance_sweep.run()

                recorded = sidecar.read(sidecar.sidecar_path(upscaled))

        self.assertEqual(recorded[provenance.BLOCK], {provenance.UPSCALE: taken_at_the_time})


class TestAGenauClip(unittest.TestCase):
    def test_a_delivered_upscale_is_recorded_as_evolvers_and_no_more(self):
        """Delivery carries a record that was already there; a loop delivered
        before anything kept one arrives with none, and its name still says the
        upscale stage made it."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                clip = touch_video(lib.genau_clips / "loop_one_topaz.mp4")

                provenance_sweep.run()

                recorded = sidecar.read(sidecar.sidecar_path(clip))

        self.assertEqual(recorded[provenance.BLOCK],
                         {provenance.UPSCALE: provenance.reconstructed("evolver")})


class TestANonAiUpscale(unittest.TestCase):
    def test_one_named_as_that_lanes_output_is_recorded_as_its_recipe_and_no_more(self):
        """The name says which recipe: apo-8 then iris-2, what the lane encodes
        with. Who ran it does not show -- the same export was made by hand in
        the Topaz GUI long before the stage existed -- so the app is unknown too."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                upscale = touch_video(
                    lib.non_ai / "alpha" / "3_good_to_go" / "processed" / "Jane-Doe-scene-1_apo8_iris2.mp4")

                provenance_sweep.run()

                recorded = sidecar.read(sidecar.sidecar_path(upscale))

        self.assertEqual(recorded[provenance.BLOCK], {
            provenance.UPSCALE_NON_AI: provenance.reconstructed(None, recipe="non_ai_upscale"),
        })


class TestRunningItAgain(unittest.TestCase):
    def test_a_library_already_recorded_is_left_alone_and_says_so(self):
        """It runs every tick, so almost every run finds nothing to do, and the
        run detail has to be able to tell that apart from a run that wrote."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no-gallery.db"):
                touch_video(lib.sorted_dir / "examplesource" / "portrait" / "clip_three.mp4")
                touch_video(lib.outbox / "portrait" / "examplesource" / "clip_three_topaz.mp4")

                provenance_sweep.run()
                again = provenance_sweep.run()

        self.assertEqual((again.unknown, again.already), (0, 1))


if __name__ == "__main__":
    unittest.main()
