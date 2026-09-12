from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import config
from util import topaz


class TestCommand(unittest.TestCase):
    def test_builds_silent_video_command(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), "the-filter", "the-tag")
        self.assertEqual(cmd[0], str(config.FFMPEG))
        self.assertIn("in.mp4", cmd)
        self.assertIn("the-filter", cmd)
        self.assertIn("videoai=the-tag", cmd)
        self.assertIn("-an", cmd)
        self.assertEqual(cmd[-1], "tmp.mp4")

    def test_keep_audio_reencodes_instead_of_stripping(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), "f", "t", keep_audio=True)
        self.assertNotIn("-an", cmd)
        self.assertIn("aac", cmd)

    def test_names_the_container_outright_since_the_file_it_writes_has_no_extension(self):
        cmd = topaz.command(Path("in.mp4"), Path("scene one.partial.ab12"), "f", "t")
        self.assertEqual(cmd[cmd.index("-f") + 1], "mp4")


# Every version a recipe has shipped under, and a fingerprint of everything that
# version runs Topaz with. A retune bumps the recipe's version in util/topaz.py
# and adds a line here for the new one; it never edits a line already here,
# because outputs on disk already name that version as what made them.
SHIPPED = {
    ("ai_upscale", "v001"): "00eb1be19cace017",
    ("ai_upscale_t2v", "v001"): "31e64e774fa2e8f4",
}


def _fingerprint(recipe: topaz.Recipe) -> str:
    """The whole command a recipe runs, bar the two file paths and the path to
    Topaz itself, which are the machine's rather than the recipe's."""
    argv = topaz.command(Path("in"), Path("out"), recipe.filter_complex, recipe.videoai_tag)
    return hashlib.sha256(json.dumps(argv[1:]).encode("utf-8")).hexdigest()[:16]


class TestARetunedRecipeOwesANewVersion(unittest.TestCase):
    def test_each_recipe_runs_the_settings_its_version_shipped_with(self):
        running = {
            (recipe.name, recipe.version): _fingerprint(recipe)
            for recipe in (topaz.AI_UPSCALE, topaz.AI_UPSCALE_T2V)
        }

        self.assertEqual(
            {key: SHIPPED.get(key) for key in running},
            running,
            "a recipe's settings changed under a version outputs already record: bump its "
            "version in util/topaz.py, then add the new version's fingerprint to SHIPPED",
        )


class TestEnvironment(unittest.TestCase):
    def test_points_topaz_at_the_model_directory(self):
        env = topaz.environment()
        self.assertEqual(env["TVAI_MODEL_DIR"], str(config.TVAI_MODEL_DIR))
        self.assertEqual(env["TVAI_MODEL_DATA_DIR"], str(config.TVAI_MODEL_DIR))


if __name__ == "__main__":
    unittest.main()
