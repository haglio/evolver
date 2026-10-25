"""Where the suite's sibling app checkouts are, and how config finds them.

The media library and the sibling apps used to share one root, so every sibling
path was derived as ``library_root / "projects" / <name>``. They no longer do:
the repos were moved out of the file-synced tree the library still lives in, so
their folders are a setting of their own, which all of Haglio shares.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from app_support import haglio_settings

import config
import content_overlay
from tests.temp_helpers import workspace_temp_dir


class TestWhatEvolverWillNotOpenWithout(unittest.TestCase):
    def _import_config_on(self, overlay: Path) -> subprocess.CompletedProcess:
        driver = ("import pathlib, content_overlay as c;"
                  f"c.LOCAL_CONTENT = pathlib.Path({str(overlay)!r});"
                  "import config")
        return subprocess.run([sys.executable, "-c", driver], cwd=content_overlay.PROJECT_DIR,
                              capture_output=True, text=True, check=False)

    def test_a_settings_file_missing_a_line_its_example_documents_stops_it_before_any_line_is_read(self):
        lines = json.loads(content_overlay.EXAMPLE_CONTENT.read_text(encoding="utf-8"))
        del lines["excerpt_folders"]
        with workspace_temp_dir() as root:
            short = root / "content.local.json"
            short.write_text(json.dumps(lines), encoding="utf-8")
            started = self._import_config_on(short)

        self.assertNotEqual(started.returncode, 0)
        self.assertIn("MissingOverlayKey", started.stderr)
        self.assertIn("excerpt_folders", started.stderr)

    def test_the_pyproject_says_it_needs_every_key_of_the_example_in_the_local_overlay(self):
        root = content_overlay.PROJECT_DIR
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "tool"]["haglio"]["opens-only-with"]
        compared = subprocess.run(
            [sys.executable, "-c", "import content_overlay as c; print(c.EXAMPLE_CONTENT); print(c.LOCAL_CONTENT)"],
            cwd=root, capture_output=True, text=True, check=True)

        self.assertEqual([root / declared["every-key-of"], root / declared["in"]],
                         [Path(line) for line in compared.stdout.splitlines()])


class TestProjectRoots(unittest.TestCase):
    def test_are_the_ones_all_of_haglio_shares(self):
        self.assertEqual(config.PROJECT_ROOTS, haglio_settings.project_roots())


class TestRetiredRoot(unittest.TestCase):
    """Where a superseded original goes once its upscale exists."""

    def test_unset_means_keep_it_in_the_library(self):
        """A public checkout gets the user's own convention: the bucket's "2*"
        folder, which is what None tells the upscale stage to use."""
        self.assertIsNone(config.retired_root({}))

    def test_an_empty_value_counts_as_unset(self):
        self.assertIsNone(config.retired_root({"retired_root": ""}))

    def test_reads_the_archive_from_the_overlay(self):
        self.assertEqual(
            config.retired_root({"retired_root": "A:/cold storage"}),
            Path("A:/cold storage"),
        )


class TestVrVideoDir(unittest.TestCase):
    def test_unset_means_the_vr_videos_sit_in_the_library(self):
        self.assertIsNone(config.vr_video_dir({}))

    def test_an_empty_value_counts_as_unset(self):
        self.assertIsNone(config.vr_video_dir({"vr_videos": ""}))

    def test_reads_where_the_vr_videos_are_kept_from_the_overlay(self):
        self.assertEqual(config.vr_video_dir({"vr_videos": "Q:/cloud/VR"}), Path("Q:/cloud/VR"))


class TestFoldersTheSharedSettingsPlace(unittest.TestCase):
    def test_each_one_is_where_the_shared_settings_say_and_nowhere_else(self):
        places = {
            "genau_dir": "Q:/example-places/genau-folder",
            "genau_audio_dir": "Q:/example-places/genau-sounds",
            "origenerator_videos_dir": "Q:/example-places/origenerator-videos",
            "warm_gun_journal_dir": "Q:/example-places/journal",
        }
        reading = (
            "import json, config; print(json.dumps({"
            "'genau_dir': str(config.GENAU_DIR), "
            "'genau_audio_dir': str(config.GENAU_AUDIO_DIR), "
            "'origenerator_videos_dir': str(config.ORIGENERATOR_VIDEOS_DIR), "
            "'warm_gun_journal_dir': str(config.WARM_GUN_JOURNAL_DIRS[0])}))"
        )
        with workspace_temp_dir() as root:
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({**copy.deepcopy(haglio_settings.EXAMPLE), **places}), encoding="utf-8")
            read = subprocess.run(
                [sys.executable, "-c", reading], cwd=config.PROJECT_DIR, check=True,
                capture_output=True, text=True,
                env={**os.environ, haglio_settings.SETTINGS_ENV: str(settings)},
            )

        self.assertEqual(json.loads(read.stdout),
                         {key: str(Path(place)) for key, place in places.items()})


class TestTopazPaths(unittest.TestCase):
    """Where Topaz Video is installed, which decides whether either upscale
    stage can run at all: they drive its own ffmpeg build and no other."""

    def test_an_overlay_that_says_nothing_gets_the_installer_s_own_paths(self):
        ffmpeg, models = config.topaz_paths({})

        self.assertEqual(ffmpeg.name, "ffmpeg.exe")
        self.assertEqual(models.name, "models")
        self.assertTrue(ffmpeg.is_absolute())
        self.assertTrue(models.is_absolute())

    def test_an_empty_value_counts_as_unset(self):
        self.assertEqual(
            config.topaz_paths({"topaz_ffmpeg": "", "topaz_models": ""}),
            config.topaz_paths({}),
        )

    def test_a_machine_that_installed_it_elsewhere_says_so_in_the_overlay(self):
        ffmpeg, models = config.topaz_paths({
            "topaz_ffmpeg": "D:/Apps/Topaz Video/ffmpeg.exe",
            "topaz_models": "E:/topaz-models",
        })

        self.assertEqual(ffmpeg, Path("D:/Apps/Topaz Video/ffmpeg.exe"))
        self.assertEqual(models, Path("E:/topaz-models"))

    def test_either_one_can_move_without_the_other(self):
        """They sit in different trees on a stock install, so an overlay that
        moves one is not saying anything about the other."""
        ffmpeg, models = config.topaz_paths({"topaz_models": "E:/topaz-models"})

        self.assertEqual(ffmpeg, config.topaz_paths({})[0])
        self.assertEqual(models, Path("E:/topaz-models"))


class TestProjectDir(unittest.TestCase):
    def test_finds_a_checkout_in_the_only_root(self):
        with workspace_temp_dir() as temp:
            checkout = temp / "suite" / "alpha_app"
            checkout.mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "suite",))

            self.assertEqual(found, checkout)

    def test_prefers_the_earlier_root_when_both_hold_the_checkout(self):
        with workspace_temp_dir() as temp:
            moved = temp / "workspace" / "alpha_app"
            moved.mkdir(parents=True)
            (temp / "old" / "alpha_app").mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "workspace", temp / "old"))

            self.assertEqual(found, moved)

    def test_falls_through_to_a_later_root_for_a_checkout_that_has_not_moved(self):
        """The half-migrated state: alpha moved, beta is still where it was."""
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "alpha_app").mkdir(parents=True)
            stayed = temp / "old" / "beta_app"
            stayed.mkdir(parents=True)

            found = config.project_dir("beta_app", (temp / "workspace", temp / "old"))

            self.assertEqual(found, stayed)

    def test_a_sibling_that_is_not_installed_still_resolves_to_a_path(self):
        """A missing sibling still resolves to a path, so callers can .is_dir() it.

        Raising here would take the whole app down over a sibling that simply
        isn't installed; every consumer already guards on existence instead.
        """
        with workspace_temp_dir() as temp:
            found = config.project_dir("gamma_app", (temp / "workspace", temp / "old"))

            self.assertEqual(found, temp / "workspace" / "gamma_app")

    def test_a_file_of_that_name_does_not_count_as_the_checkout(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace").mkdir()
            (temp / "workspace" / "alpha_app").write_text("not a checkout", encoding="utf-8")
            checkout = temp / "old" / "alpha_app"
            checkout.mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "workspace", temp / "old"))

            self.assertEqual(found, checkout)


class TestLiveDir(unittest.TestCase):
    """Which checkout's run history, log, settings and queue lists a run uses.

    Its own, except in a branch session: the preview launcher runs a worktree's
    whole app beside the live one, and a preview keeping those files for itself
    would show a history nobody made and a queue nobody ordered.
    """

    def test_an_ordinary_run_uses_its_own_checkout(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "evolver").mkdir(parents=True)

            found = config.live_dir({}, temp / "worktree", (temp / "workspace",))

            self.assertEqual(found, temp / "worktree")

    def test_a_branch_session_uses_the_checkout_the_live_app_runs_from(self):
        with workspace_temp_dir() as temp:
            live = temp / "workspace" / "evolver"
            live.mkdir(parents=True)

            found = config.live_dir({config.BRANCH_SESSION_FLAG: "1"},
                                    temp / "worktree", (temp / "workspace",))

            self.assertEqual(found, live)

    def test_only_the_flag_the_preview_launcher_sets_counts(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "evolver").mkdir(parents=True)

            found = config.live_dir({config.BRANCH_SESSION_FLAG: "yes"},
                                    temp / "worktree", (temp / "workspace",))

            self.assertEqual(found, temp / "worktree")


class TestSiblingPathsUseTheProjectRoots(unittest.TestCase):
    """The four sibling paths must come from the roots, not from the library root."""

    def test_every_sibling_path_sits_under_one_of_the_project_roots(self):
        for name, path in (
            ("FUN_TIME_PROJECT_DIR", config.FUN_TIME_PROJECT_DIR),
            ("ORIGENERATOR_DB_PATH", config.ORIGENERATOR_DB_PATH),
            ("GENAUMACHER_SESSIONS_DIR", config.GENAUMACHER_SESSIONS_DIR),
            ("SCRIPTURE_SESSIONS_DIR", config.SCRIPTURE_SESSIONS_DIR),
        ):
            with self.subTest(name):
                self.assertTrue(
                    any(path.is_relative_to(root) for root in config.PROJECT_ROOTS),
                    f"{name} ({path}) is under none of {config.PROJECT_ROOTS}",
                )

    def test_the_derived_sibling_files_stay_anchored_to_the_fun_time_checkout(self):
        for path in (config.FUN_TIME_FAVS_FILE, config.FUN_TIME_WATCH_STATS_FILE):
            with self.subTest(str(path)):
                self.assertTrue(path.is_relative_to(config.FUN_TIME_PROJECT_DIR))


if __name__ == "__main__":
    unittest.main()


class TestWarmGunJournalDirs(unittest.TestCase):
    def test_the_library_holds_the_journal_when_the_overlay_says_nothing(self):
        self.assertEqual(
            config.warm_gun_journal_dirs({}, Path("L:/library/app_data/warm_gun")),
            (Path("L:/library/app_data/warm_gun"),),
        )

    def test_the_folder_the_phone_still_writes_to_is_read_as_well(self):
        self.assertEqual(
            config.warm_gun_journal_dirs({"warm_gun_outbox": "S:/WarmGun"},
                                         Path("L:/library/app_data/warm_gun")),
            (Path("L:/library/app_data/warm_gun"), Path("S:/WarmGun")),
        )

    def test_an_empty_value_counts_as_unset(self):
        self.assertEqual(
            len(config.warm_gun_journal_dirs({"warm_gun_outbox": ""},
                                             Path("L:/library/app_data/warm_gun"))), 1
        )

    def test_the_phone_s_own_folder_is_the_one_the_overlay_names(self):
        self.assertEqual(config.warm_gun_outbox({"warm_gun_outbox": "S:/WarmGun"}), Path("S:/WarmGun"))

    def test_with_none_named_the_phone_has_no_folder_of_its_own(self):
        self.assertIsNone(config.warm_gun_outbox({"warm_gun_outbox": ""}))
