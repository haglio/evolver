from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app_support import haglio_settings

import config
import content_overlay
from tasks.nonai_encode import EncodeSettings
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

        assert started.returncode != 0
        assert "MissingOverlayKey" in started.stderr
        assert "excerpt_folders" in started.stderr

    def test_the_pyproject_says_it_needs_every_key_of_the_example_in_the_local_overlay(self):
        root = content_overlay.PROJECT_DIR
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "tool"]["haglio"]["opens-only-with"]
        compared = subprocess.run(
            [sys.executable, "-c", "import content_overlay as c; print(c.EXAMPLE_CONTENT); print(c.LOCAL_CONTENT)"],
            cwd=root, capture_output=True, text=True, check=True)

        assert [root / declared["every-key-of"], root / declared["in"]] == [Path(line) for line in compared.stdout.splitlines()]


class TestProjectRoots(unittest.TestCase):
    def test_are_the_ones_all_of_haglio_shares(self):
        assert haglio_settings.project_roots() == config.PROJECT_ROOTS


class TestRetiredRoot(unittest.TestCase):
    def test_unset_keeps_the_original_in_the_buckets_own_2_folder_as_filed_by_hand(self):
        assert config.retired_root({}) is None

    def test_an_empty_value_counts_as_unset(self):
        assert config.retired_root({"retired_root": ""}) is None

    def test_an_archive_in_the_overlay_takes_originals_off_the_drive_the_encodes_fill(self):
        assert config.retired_root({"retired_root": "A:/cold storage"}) == Path("A:/cold storage")


class TestVrVideoDir(unittest.TestCase):
    def test_unset_means_the_vr_videos_sit_in_the_library(self):
        assert config.vr_video_dir({}) is None

    def test_an_empty_value_counts_as_unset(self):
        assert config.vr_video_dir({"vr_videos": ""}) is None

    def test_reads_where_the_vr_videos_are_kept_from_the_overlay(self):
        assert config.vr_video_dir({"vr_videos": "Q:/cloud/VR"}) == Path("Q:/cloud/VR")


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

        assert json.loads(read.stdout) == {key: str(Path(place)) for key, place in places.items()}


class TestTopazPaths(unittest.TestCase):

    def test_an_overlay_that_says_nothing_gets_the_installer_s_own_paths(self):
        ffmpeg, models = config.topaz_paths({})

        assert ffmpeg.name == "ffmpeg.exe"
        assert models.name == "models"
        assert ffmpeg.is_absolute()
        assert models.is_absolute()

    def test_an_empty_value_counts_as_unset(self):
        assert config.topaz_paths({"topaz_ffmpeg": "", "topaz_models": ""}) == config.topaz_paths({})

    def test_a_computer_that_installed_it_elsewhere_says_so_in_the_overlay(self):
        ffmpeg, models = config.topaz_paths({
            "topaz_ffmpeg": "D:/Apps/Topaz Video/ffmpeg.exe",
            "topaz_models": "E:/topaz-models",
        })

        assert ffmpeg == Path("D:/Apps/Topaz Video/ffmpeg.exe")
        assert models == Path("E:/topaz-models")

    def test_either_one_can_move_without_the_other(self):
        ffmpeg, models = config.topaz_paths({"topaz_models": "E:/topaz-models"})

        assert ffmpeg == config.topaz_paths({})[0]
        assert models == Path("E:/topaz-models")


class TestProjectDir(unittest.TestCase):
    def test_finds_a_checkout_in_the_only_root(self):
        with workspace_temp_dir() as temp:
            checkout = temp / "suite" / "alpha_app"
            checkout.mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "suite",))

            assert found == checkout

    def test_prefers_the_earlier_root_when_both_hold_the_checkout(self):
        with workspace_temp_dir() as temp:
            moved = temp / "workspace" / "alpha_app"
            moved.mkdir(parents=True)
            (temp / "old" / "alpha_app").mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "workspace", temp / "old"))

            assert found == moved

    def test_falls_through_to_a_later_root_for_a_checkout_that_has_not_moved(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "alpha_app").mkdir(parents=True)
            stayed = temp / "old" / "beta_app"
            stayed.mkdir(parents=True)

            found = config.project_dir("beta_app", (temp / "workspace", temp / "old"))

            assert found == stayed

    def test_a_sibling_that_is_not_installed_still_resolves_to_a_path_so_importing_config_never_crashes(self):
        with workspace_temp_dir() as temp:
            found = config.project_dir("gamma_app", (temp / "workspace", temp / "old"))

            assert found == temp / "workspace" / "gamma_app"

    def test_a_file_of_that_name_does_not_count_as_the_checkout(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace").mkdir()
            (temp / "workspace" / "alpha_app").write_text("not a checkout", encoding="utf-8")
            checkout = temp / "old" / "alpha_app"
            checkout.mkdir(parents=True)

            found = config.project_dir("alpha_app", (temp / "workspace", temp / "old"))

            assert found == checkout


class TestLiveDir(unittest.TestCase):
    def test_an_ordinary_run_uses_its_own_checkout(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "evolver").mkdir(parents=True)

            found = config.live_dir({}, temp / "worktree", (temp / "workspace",))

            assert found == temp / "worktree"

    def test_a_branch_session_shows_the_production_checkouts_real_run_history_and_queues(self):
        with workspace_temp_dir() as temp:
            live = temp / "workspace" / "evolver"
            live.mkdir(parents=True)

            found = config.live_dir({config.BRANCH_SESSION_FLAG: "1"},
                                    temp / "worktree", (temp / "workspace",))

            assert found == live

    def test_only_the_flag_the_preview_launcher_sets_counts(self):
        with workspace_temp_dir() as temp:
            (temp / "workspace" / "evolver").mkdir(parents=True)

            found = config.live_dir({config.BRANCH_SESSION_FLAG: "yes"},
                                    temp / "worktree", (temp / "workspace",))

            assert found == temp / "worktree"


class TestSiblingPathsUseTheProjectRoots(unittest.TestCase):
    def test_every_sibling_path_sits_under_one_of_the_project_roots(self):
        for name, path in (
            ("FUN_TIME_PROJECT_DIR", config.FUN_TIME_PROJECT_DIR),
            ("ORIGENERATOR_DB_PATH", config.ORIGENERATOR_DB_PATH),
            ("GENAUMACHER_SESSIONS_DIR", config.GENAUMACHER_SESSIONS_DIR),
            ("SCRIPTURE_SESSIONS_DIR", config.SCRIPTURE_SESSIONS_DIR),
        ):
            with self.subTest(name):
                assert any(path.is_relative_to(root) for root in config.PROJECT_ROOTS), f"{name} ({path}) is under none of {config.PROJECT_ROOTS}"

    def test_the_derived_sibling_files_stay_anchored_to_the_fun_time_checkout(self):
        assert config.FUN_TIME_WATCH_STATS_FILE.is_relative_to(config.FUN_TIME_PROJECT_DIR)


class TestWarmGunJournalDirs(unittest.TestCase):
    def test_the_synced_library_is_the_journals_home_when_the_overlay_says_nothing(self):
        assert config.warm_gun_journal_dirs({}, Path("L:/library/app_data/warm_gun")) == (Path("L:/library/app_data/warm_gun"),)

    def test_the_outbox_the_phone_writes_to_until_it_is_retired_is_read_as_well(self):
        assert config.warm_gun_journal_dirs({"warm_gun_outbox": "S:/WarmGun"}, Path("L:/library/app_data/warm_gun")) == (Path("L:/library/app_data/warm_gun"), Path("S:/WarmGun"))

    def test_an_empty_value_counts_as_unset(self):
        assert len(config.warm_gun_journal_dirs({"warm_gun_outbox": ""}, Path("L:/library/app_data/warm_gun"))) == 1

    def test_the_phone_s_own_folder_is_the_one_the_overlay_names(self):
        assert config.warm_gun_outbox({"warm_gun_outbox": "S:/WarmGun"}) == Path("S:/WarmGun")

    def test_with_none_named_the_phone_has_no_folder_of_its_own(self):
        assert config.warm_gun_outbox({"warm_gun_outbox": ""}) is None


class TestTheOverlayPath(unittest.TestCase):
    def test_is_read_at_each_call_so_the_suite_can_point_every_reader_at_the_example(self):
        with workspace_temp_dir() as root:
            elsewhere = root / "content.local.json"
            elsewhere.write_text(json.dumps({"chrome_profile": "Profile 9"}), encoding="utf-8")
            with patch.object(content_overlay, "LOCAL_CONTENT", elsewhere):
                assert content_overlay.load_content()["chrome_profile"] == "Profile 9"


class TestDisplayTimezone(unittest.TestCase):
    def test_unset_leaves_the_zone_to_windows_for_a_computer_in_its_users_own_zone(self):
        assert config.display_timezone({}) is None

    def test_a_computer_away_from_the_zone_its_user_reads_names_that_zone_in_the_overlay(self):
        assert config.display_timezone({"display_timezone": "Asia/Tokyo"}) == ZoneInfo("Asia/Tokyo")


class TestTheEncodeAndTheRun(unittest.TestCase):
    def test_what_one_encode_may_cost_the_computer_is_encode_settings_never_config(self):
        settings = {name.upper() for name in EncodeSettings.__dataclass_fields__}

        assert sorted(name for name in vars(config) if name.removeprefix("NONAI_") in settings) == []

    def test_a_returning_user_parks_the_encode_within_seconds_rather_than_at_the_next_run(self):
        assert config.NONAI_PRESENCE_POLL_SECONDS < 60


if __name__ == "__main__":
    unittest.main()
