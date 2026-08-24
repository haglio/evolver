"""Tests for gui.taskbar — Windows taskbar pin properties."""

import unittest
from unittest.mock import patch

from gui.taskbar import set_taskbar_properties
from tests.gui_support import build_evolver_app


class TestSetTaskbarProperties(unittest.TestCase):

    def test_does_not_raise_on_invalid_hwnd(self):
        # An invalid HWND should be caught and logged, not raised
        set_taskbar_properties(0, "Test.App", "test.exe", "Test", "test.ico")


class TestAppSetsTaskbarProperties(unittest.TestCase):

    def test_evolver_app_sets_taskbar_pin_properties(self):
        from gui.app import _APP_MODEL_ID

        with patch("gui.app.set_taskbar_properties") as mock_set:
            build_evolver_app(self)

        mock_set.assert_called_once()
        args = mock_set.call_args
        # First arg is HWND (int), second is the app model ID
        self.assertEqual(args[0][1], _APP_MODEL_ID)
        # Display name should be "Evolver"
        self.assertEqual(args[0][3], "Evolver")


if __name__ == "__main__":
    unittest.main()
