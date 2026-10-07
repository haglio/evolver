"""What Evolver's window tells the taskbar about the app it belongs to."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

from shared_ui.preview import Preview

import config
from gui.process_identity import APP_MODEL_ID
from tests.gui_support import build_evolver_app
from tests.temp_helpers import override_config


def _dressed(request) -> tuple:
    app = build_evolver_app(request)
    with patch("gui.process_identity.set_app_user_model_id"), \
         patch("gui.process_identity.dress_window") as dress:
        app.start()
    dress.assert_called_once()
    _hwnd, app_id, taskbar_app = dress.call_args.args
    return app_id, taskbar_app


class TestTheWindowOnTheTaskbar:

    def test_the_everyday_evolver_is_dressed_as_evolver(self, request):
        app_id, taskbar_app = _dressed(request)

        # The AppUserModelID is a Windows identity contract: it is what makes a
        # pinned taskbar shortcut belong to Evolver rather than to pythonw, so
        # the literal is pinned here beside the constant.
        assert app_id == "Evolver.TrayApp" == APP_MODEL_ID
        assert taskbar_app.name == "Evolver"
        assert taskbar_app.icon == config.PROJECT_DIR / "icon.ico"

    def test_a_preview_is_dressed_in_its_amber_letter(self, request, tmp_path: Path):
        with override_config(BRANCH_SESSION=True, LOCAL_STATE_DIR=tmp_path), \
             patch("util.preview.preview_of", return_value=Preview(feature="a feature")):
            app_id, taskbar_app = _dressed(request)

        assert app_id == f"{APP_MODEL_ID}.Preview"
        assert taskbar_app.name.startswith("Evolver — preview of a feature")
        assert taskbar_app.icon == tmp_path / "preview_icon.ico"
        assert taskbar_app.icon.is_file()

    def test_a_window_windows_will_not_dress_is_said_not_raised(self, request, caplog):
        app = build_evolver_app(request)
        with patch("gui.process_identity.set_app_user_model_id"), \
             patch("gui.process_identity.dress_window",
                   side_effect=OSError("SHGetPropertyStoreForWindow failed")), \
             caplog.at_level(logging.WARNING, logger="gui.process_identity"):
            app.start()

        assert any("taskbar" in record.message.lower() for record in caplog.records)
