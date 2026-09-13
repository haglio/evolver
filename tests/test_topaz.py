from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import config
from util import orientation, topaz

_EXAMPLE = topaz.Recipe(name="example", version="v000",
                        filter_complex="the-filter", videoai_tag="the-tag")


class TestCommand(unittest.TestCase):
    def test_builds_silent_video_command(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), _EXAMPLE)
        self.assertEqual(cmd[0], str(config.FFMPEG))
        self.assertIn("in.mp4", cmd)
        self.assertIn("the-filter", cmd)
        self.assertIn("videoai=the-tag", cmd)
        self.assertIn("-an", cmd)
        self.assertEqual(cmd[-1], "tmp.mp4")

    def test_keep_audio_reencodes_instead_of_stripping(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), replace(_EXAMPLE, keep_audio=True))
        self.assertNotIn("-an", cmd)
        self.assertIn("aac", cmd)

    def test_names_the_container_outright_since_the_file_it_writes_has_no_extension(self):
        cmd = topaz.command(Path("in.mp4"), Path("scene one.partial.ab12"), _EXAMPLE)
        self.assertEqual(cmd[cmd.index("-f") + 1], "mp4")

    def test_a_recipe_aimed_at_a_frame_is_refused_until_it_is_turned_to_the_video(self):
        """Unframed, its filter would reach Topaz still asking for {width}."""
        with self.assertRaises(ValueError):
            topaz.command(Path("in.mp4"), Path("tmp.mp4"), topaz.NON_AI_UPSCALE)


# Every version a recipe has shipped under, and a fingerprint of everything that
# version runs Topaz with. A retune bumps the recipe's version in util/topaz.py
# and adds a line here for the new one; it never edits a line already here,
# because outputs on disk already name that version as what made them.
SHIPPED = {
    ("ai_upscale", "v001"): "ba105a7372baef8f",
    ("ai_upscale_t2v", "v001"): "433ce5942b2b7849",
    ("non_ai_upscale", "v001"): "7abba8acb076bb73",
}


def _fingerprint(recipe: topaz.Recipe) -> str:
    """Every command a recipe runs -- one per orientation -- bar the two file
    paths and the path to Topaz itself, which are the machine's, not the recipe's."""
    argvs = [
        topaz.command(Path("in"), Path("out"),
                      topaz.framed(recipe, orient) if recipe.frame else recipe)[1:]
        for orient in orientation.SORTED
    ]
    return hashlib.sha256(json.dumps(argvs).encode("utf-8")).hexdigest()[:16]


class TestARetunedRecipeOwesANewVersion(unittest.TestCase):
    def test_each_recipe_runs_the_settings_its_version_shipped_with(self):
        running = {(recipe.name, recipe.version): _fingerprint(recipe) for recipe in topaz.RECIPES}

        self.assertEqual(
            {key: SHIPPED.get(key) for key in running},
            running,
            "a recipe's settings changed under a version outputs already record: bump its "
            "version in util/topaz.py, then add the new version's fingerprint to SHIPPED",
        )


class TestWhatAFilesNoteSaysMadeIt(unittest.TestCase):
    def test_a_note_in_a_recipes_own_words_names_that_recipe(self):
        for recipe in topaz.RECIPES:
            with self.subTest(recipe=recipe.name):
                self.assertIs(topaz.recipe_noted(recipe.videoai_tag), recipe)

    def test_a_note_differing_only_in_the_name_in_parentheses_at_its_end_names_it_too(self):
        """The text-to-video recipe's note once named a site in those parentheses,
        and the files written then still say which recipe made them."""
        note = topaz.AI_UPSCALE_T2V.videoai_tag
        written_then = note[:note.rindex("(")] + "(t2v examplesite)"

        self.assertNotEqual(written_then, note)
        self.assertIs(topaz.recipe_noted(written_then), topaz.AI_UPSCALE_T2V)

    def test_a_note_in_topazs_own_words_or_no_note_at_all_names_no_recipe(self):
        """Topaz describes an export made by hand in its own phrasing; that, or a
        file carrying no note, was not made by any recipe here."""
        for note in (("Processed using apo-8 replacing duplicate frames. Enhanced using gcg-5. "
                      "4x upscale"), ""):
            with self.subTest(note=note):
                self.assertIsNone(topaz.recipe_noted(note))


class TestEnvironment(unittest.TestCase):
    def test_points_topaz_at_the_model_directory(self):
        env = topaz.environment()
        self.assertEqual(env["TVAI_MODEL_DIR"], str(config.TVAI_MODEL_DIR))
        self.assertEqual(env["TVAI_MODEL_DATA_DIR"], str(config.TVAI_MODEL_DIR))


def topaz_check_reporting(log: str):
    return patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", log))


class TestSignInExpired(unittest.TestCase):
    def test_topaz_saying_its_sign_in_token_expired_means_the_sign_in_expired(self):
        log = ("INFO:  Authentication token expired\n"
               "INFO:  Will attempt to refresh\n"
               "INFO:  Refresh succeeded. Reusing existing license.\n")
        with topaz_check_reporting(log):
            self.assertTrue(topaz.sign_in_expired())

    def test_topaz_failing_to_authenticate_or_turning_its_watermark_on_means_the_same(self):
        for log in ("ERROR: Authentication Failure: login to your account using the login tool\n",
                    "WARNING: Refresh failed. Watermark will be enabled\n"):
            with self.subTest(log=log), topaz_check_reporting(log):
                self.assertTrue(topaz.sign_in_expired())

    def test_a_check_that_reports_no_expiry_means_the_sign_in_is_good(self):
        with topaz_check_reporting("INFO:  Relogin valid\nINFO:  Auth Check Watermark: 0 0 0\n"):
            self.assertFalse(topaz.sign_in_expired())

    def test_the_check_is_a_tiny_verbose_topaz_run_with_no_window_and_a_time_limit(self):
        with topaz_check_reporting("") as run:
            topaz.sign_in_expired()

        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(argv[0], str(config.FFMPEG))
        self.assertEqual(argv[argv.index("-loglevel") + 1], "verbose")
        self.assertIn("tvai_up", argv[argv.index("-vf") + 1])
        self.assertEqual(argv[-3:], ["-f", "null", "-"])
        self.assertEqual(kwargs["env"]["TVAI_MODEL_DIR"], str(config.TVAI_MODEL_DIR))
        self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
        self.assertGreater(kwargs["timeout"], 0)

    def test_a_check_that_cannot_run_does_not_claim_the_sign_in_expired(self):
        for failure in (OSError("no ffmpeg"), subprocess.TimeoutExpired("ffmpeg", 90)):
            with self.subTest(failure=failure), \
                 patch("subprocess.run", side_effect=failure), \
                 self.assertLogs("util.topaz", level="WARNING"):
                self.assertFalse(topaz.sign_in_expired())


if __name__ == "__main__":
    unittest.main()
