from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support.testing import error_popup
from PyQt6.QtWidgets import QApplication
from shared_ui.alert import Link
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview
from shared_ui.testing import alert_shown

from tests.product_sources import PROJECT_ROOT, product_sources
from util import alert


class TestTheOnlyWayToAModalDialog(unittest.TestCase):
    @pytest.mark.repo_check
    def test_no_other_module_opens_a_dialog_for_itself(self):
        openers = [
            name
            for name in product_sources(PROJECT_ROOT)
            if any(
                reached in Path(PROJECT_ROOT, name).read_text(encoding="utf-8")
                for reached in ("shared_ui.alert", "show_error_popup")
            )
        ]

        assert openers == ["util/alert.py"]


class TestShowError(unittest.TestCase):
    @alert_shown()
    def test_it_opens_the_familys_dialog_under_evolvers_own_icon(self, show_alert):
        alert.show_error("Title", "Body")

        show_alert.assert_called_once_with(
            "Title", "Body", icon=alert.ICON_FILE, links=[], dismissible=False)

    @alert_shown()
    def test_a_previews_alert_wears_its_letter_in_the_preview_ink(self, show_alert):
        _app = QApplication.instance() or QApplication([])
        with patch("util.preview.shown_as", return_value=Preview(feature=None)):
            alert.show_error("Title", "Body")

        letter = show_alert.call_args.kwargs["icon"].pixmap(256, 256).toImage().pixelColor(128, 128)
        assert (letter.red(), letter.green(), letter.blue()) == PREVIEW_INK

    @alert_shown()
    def test_a_folder_to_open_reaches_the_dialog_as_a_link_under_the_message(self, show_alert):
        folder = Path("library", "scripts", "alpha")

        alert.show_error("Title", "Body", links=[("Open its folder", folder)])

        show_alert.assert_called_once_with(
            "Title", "Body", icon=alert.ICON_FILE, links=[Link("Open its folder", folder)],
            dismissible=False)

    @alert_shown(return_value=True)
    def test_an_alert_that_offers_dismiss_says_whether_it_was_dismissed(self, show_alert):
        dismissed = alert.show_error("Title", "Body", dismissible=True)

        assert dismissed is True
        assert show_alert.call_args.kwargs["dismissible"] is True

    @error_popup()
    @alert_shown(side_effect=ImportError("no Qt"))
    def test_a_dialog_that_will_not_open_falls_back_to_the_windows_one(
        self, _show_alert, show_error_popup,
    ):
        with self.assertLogs("util.alert", level="ERROR") as logged:
            alert.show_error("Title", "Body")

        show_error_popup.assert_called_once_with("Title", "Body")
        assert "Title" in logged.records[0].getMessage()

    @error_popup()
    @alert_shown(side_effect=ImportError("no Qt"))
    def test_the_windows_dialog_spells_out_the_folders_it_cannot_link_to(
        self, _show_alert, show_error_popup,
    ):
        folder = Path("library", "scripts", "alpha")

        with self.assertLogs("util.alert", level="ERROR"):
            alert.show_error("Title", "Body", links=[("Open its folder", folder)])

        show_error_popup.assert_called_once_with("Title", f"Body\n\n{folder}")

    @error_popup()
    @alert_shown(side_effect=ImportError("no Qt"))
    def test_the_windows_dialog_has_no_dismiss_so_it_comes_back(self, _show_alert, _popup):
        with self.assertLogs("util.alert", level="ERROR"):
            dismissed = alert.show_error("Title", "Body", dismissible=True)

        assert dismissed is False

    @error_popup(side_effect=OSError("no user32"))
    @alert_shown(side_effect=ImportError("no Qt"))
    def test_a_stage_that_already_failed_does_not_fail_again_saying_so(
        self, _show_alert, _show_error_popup,
    ):
        with self.assertLogs("util.alert", level="ERROR"):
            alert.show_error("Title", "Body")


if __name__ == "__main__":
    unittest.main()
