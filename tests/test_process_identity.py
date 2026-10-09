"""What every window an Evolver process shows tells the taskbar about the app it belongs to."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QImage
from PyQt6.QtWidgets import QWidget
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

import config
from gui import process_identity
from gui.process_identity import APP_MODEL_ID
from tests.gui_support import QAPP
from tests.temp_helpers import override_config


@pytest.fixture
def claimed():
    claims: list[str] = []
    worn: list[tuple] = []
    dressers: list[QObject] = []
    icon_before = QAPP.windowIcon()

    def claim():
        dressers.append(process_identity.claim(QAPP))
        return claims, worn

    with patch("gui.process_identity.set_app_user_model_id", side_effect=claims.append), \
         patch("gui.process_identity.dress_window", side_effect=lambda *dressing: worn.append(dressing)):
        yield claim
    for dresser in dressers:
        QAPP.removeEventFilter(dresser)
    QAPP.setWindowIcon(icon_before)


def _shown(request, window: QWidget) -> QWidget:
    window.show()
    request.addfinalizer(window.close)
    return window


def _drawn(icon: QIcon) -> QImage:
    return icon.pixmap(256, 256).toImage()


class TestEveryWindowOnTheTaskbar:

    def test_the_everyday_evolver_claims_evolver_and_dresses_each_window_as_evolver(
            self, claimed, request):
        claims, worn = claimed()
        window = _shown(request, QWidget())

        # The AppUserModelID is a Windows identity contract: it is what makes a
        # pinned taskbar shortcut belong to Evolver rather than to pythonw, so
        # the literal is pinned here beside the constant.
        assert claims == ["Evolver.TrayApp"] == [APP_MODEL_ID]
        [(hwnd, app_id, taskbar_app)] = worn
        assert hwnd == int(window.winId())
        assert app_id == APP_MODEL_ID
        assert taskbar_app.name == "Evolver"
        assert taskbar_app.icon == config.PROJECT_DIR / "icon.ico"

    def test_a_preview_dresses_each_window_in_its_amber_letter(self, claimed, request, tmp_path: Path):
        with override_config(BRANCH_SESSION=True, LOCAL_STATE_DIR=tmp_path), \
             patch("util.preview.preview_of", return_value=Preview(feature="a feature")):
            claims, worn = claimed()
        _shown(request, QWidget())

        [(_hwnd, app_id, taskbar_app)] = worn
        assert claims == [app_id] == [f"{APP_MODEL_ID}.Preview"]
        assert taskbar_app.name.startswith("Evolver — preview of a feature")
        assert taskbar_app.icon == tmp_path / "preview_icon.ico"
        assert taskbar_app.icon.is_file()

    def test_each_window_wears_evolvers_letter(self, claimed):
        QAPP.setWindowIcon(QIcon())

        claimed()

        assert _drawn(QAPP.windowIcon()) == _drawn(QIcon(str(config.PROJECT_DIR / "icon.ico")))

    def test_each_window_of_a_preview_wears_the_letter_in_the_preview_ink(self, claimed, tmp_path: Path):
        with override_config(BRANCH_SESSION=True, LOCAL_STATE_DIR=tmp_path), \
             patch("util.preview.preview_of", return_value=Preview(feature=None)):
            claimed()

        middle_of_the_e = _drawn(QAPP.windowIcon()).pixelColor(128, 128)
        assert (middle_of_the_e.red(), middle_of_the_e.green(), middle_of_the_e.blue()) == PREVIEW_INK

    def test_what_a_window_holds_is_left_to_the_window(self, claimed, request):
        _claims, worn = claimed()
        window = QWidget()
        QWidget(window)

        _shown(request, window)

        assert len(worn) == 1

    def test_a_window_windows_will_not_dress_still_opens_and_says_so(self, claimed, request, caplog):
        claimed()
        with patch("gui.process_identity.dress_window",
                   side_effect=OSError("SHGetPropertyStoreForWindow failed")), \
             caplog.at_level(logging.WARNING, logger="gui.process_identity"):
            window = _shown(request, QWidget())

        assert window.isVisible()
        assert any("taskbar" in record.message.lower() for record in caplog.records)
