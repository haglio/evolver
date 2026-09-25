from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from shared_ui.alert import Link

from tests.product_sources import PROJECT_ROOT, product_sources
from util import alert


class TestTheOnlyWayToAModalDialog(unittest.TestCase):
    def test_no_other_module_opens_a_dialog_for_itself(self):
        """``tests/__init__.py`` gags the two calls ``util/alert.py`` makes.

        That gag covers this module and nothing else, so a second module
        reaching either of them for itself would block an unattended run on a
        human -- the failure the gag exists to make impossible.
        """
        openers = [
            name
            for name in product_sources(PROJECT_ROOT)
            if any(
                reached in Path(PROJECT_ROOT, name).read_text(encoding="utf-8")
                for reached in ("shared_ui.alert", "show_error_popup")
            )
        ]

        self.assertEqual(openers, ["util/alert.py"])


class TestShowError(unittest.TestCase):
    @patch("shared_ui.alert.show_alert")
    def test_it_opens_the_familys_dialog_under_evolvers_own_icon(self, show_alert):
        alert.show_error("Title", "Body")

        show_alert.assert_called_once_with("Title", "Body", icon=alert.ICON_FILE, links=[])

    @patch("shared_ui.alert.show_alert")
    def test_a_folder_to_open_reaches_the_dialog_as_a_link_under_the_message(self, show_alert):
        folder = Path("library", "scripts", "alpha")

        alert.show_error("Title", "Body", links=[("Open its folder", folder)])

        show_alert.assert_called_once_with(
            "Title", "Body", icon=alert.ICON_FILE, links=[Link("Open its folder", folder)])

    @patch("app_support.win32.show_error_popup")
    @patch("shared_ui.alert.show_alert", side_effect=ImportError("no Qt"))
    def test_a_dialog_that_will_not_open_falls_back_to_the_windows_one(
        self, _show_alert, show_error_popup,
    ):
        """The startup crash reporter runs on an interpreter that has just
        failed to import something; Qt is a candidate for what it failed on,
        and a crash nobody is shown is indistinguishable from a launcher that
        did nothing."""
        with self.assertLogs("util.alert", level="ERROR") as logged:
            alert.show_error("Title", "Body")

        show_error_popup.assert_called_once_with("Title", "Body")
        self.assertIn("Title", logged.records[0].getMessage())

    @patch("app_support.win32.show_error_popup")
    @patch("shared_ui.alert.show_alert", side_effect=ImportError("no Qt"))
    def test_the_windows_dialog_spells_out_the_folders_it_cannot_link_to(
        self, _show_alert, show_error_popup,
    ):
        folder = Path("library", "scripts", "alpha")

        with self.assertLogs("util.alert", level="ERROR"):
            alert.show_error("Title", "Body", links=[("Open its folder", folder)])

        show_error_popup.assert_called_once_with("Title", f"Body\n\n{folder}")

    @patch("app_support.win32.show_error_popup", side_effect=OSError("no user32"))
    @patch("shared_ui.alert.show_alert", side_effect=ImportError("no Qt"))
    def test_a_stage_that_already_failed_does_not_fail_again_saying_so(
        self, _show_alert, _show_error_popup,
    ):
        with self.assertLogs("util.alert", level="ERROR"):
            alert.show_error("Title", "Body")


if __name__ == "__main__":
    unittest.main()
