"""Tests for gui.taskbar — Windows taskbar pin properties."""

from unittest.mock import patch

from gui.taskbar import set_taskbar_properties
from tests.gui_support import build_evolver_app


class TestSetTaskbarProperties:

    def test_an_invalid_hwnd_is_logged_not_raised(self, caplog):
        """Taskbar cosmetics must never crash the app, but must not fail
        silently either -- the warning is the observable outcome, and asserting
        it is what separates 'the error path ran' from 'the call returned'."""
        import logging

        with caplog.at_level(logging.WARNING, logger="gui.taskbar"):
            set_taskbar_properties(0, "Test.App", "test.exe", "Test", "test.ico")
        assert any(
            "taskbar" in record.message.lower() for record in caplog.records
        ), "no warning was logged for the invalid HWND"


class TestAppSetsTaskbarProperties:

    def test_evolver_app_sets_taskbar_pin_properties(self, request):
        from gui.process_identity import APP_MODEL_ID

        app = build_evolver_app(request)
        with patch("gui.process_identity.set_taskbar_properties") as mock_set:
            app.start()

        mock_set.assert_called_once()
        args = mock_set.call_args
        # The AppUserModelID is a Windows identity contract: it is what makes a
        # pinned taskbar shortcut belong to Evolver rather than to pythonw, so
        # the literal is pinned here, beside the display name -- comparing the
        # call against the imported constant accepted any value at all.
        assert args[0][1] == "Evolver.TrayApp"
        assert args[0][1] == APP_MODEL_ID
        # Display name should be "Evolver"
        assert args[0][3] == "Evolver"
