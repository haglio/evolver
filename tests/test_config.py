"""Where the suite's sibling app checkouts are, and how config finds them.

The media library and the sibling apps used to share one root, so every sibling
path was derived as ``library_root / "projects" / <name>``. They no longer do:
the repos were moved out of the file-synced tree the library still lives in, so
their root is its own setting. These tests pin the resolution rules, including
the half-migrated state where some checkouts have moved and some have not.
"""

import unittest
from pathlib import Path

import config
from tests.temp_helpers import workspace_temp_dir


class TestProjectRoots(unittest.TestCase):
    def test_defaults_to_the_projects_folder_under_the_library_root(self):
        """An overlay with no project_roots behaves exactly as it always did."""
        roots = config.project_roots({}, Path("L:/library"))

        self.assertEqual(roots, (Path("L:/library/projects"),))

    def test_an_empty_list_falls_back_to_the_default_too(self):
        roots = config.project_roots({"project_roots": []}, Path("L:/library"))

        self.assertEqual(roots, (Path("L:/library/projects"),))

    def test_reads_the_roots_from_the_overlay_in_the_order_given(self):
        roots = config.project_roots(
            {"project_roots": ["W:/workspace/suite", "L:/library/projects"]},
            Path("L:/library"),
        )

        self.assertEqual(roots, (Path("W:/workspace/suite"), Path("L:/library/projects")))


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

    def test_returns_a_path_under_the_first_root_when_no_root_holds_it(self):
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


class TestSiblingPathsUseTheProjectRoots(unittest.TestCase):
    """The four sibling paths must come from the roots, not from the library root."""

    def test_every_sibling_path_sits_under_one_of_the_project_roots(self):
        for name, path in (
            ("FUN_TIME_PROJECT_DIR", config.FUN_TIME_PROJECT_DIR),
            ("ORIGENERATOR_DB_PATH", config.ORIGENERATOR_DB_PATH),
            ("CLIPPER_SESSIONS_DIR", config.CLIPPER_SESSIONS_DIR),
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
