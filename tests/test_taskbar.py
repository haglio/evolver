"""Tests for gui.taskbar — Windows taskbar pin properties."""

import unittest
from unittest.mock import patch

from gui.taskbar import _guid_bytes, set_taskbar_properties


class TestGuidBytes(unittest.TestCase):

    def test_encodes_ipropertystore_iid(self):
        # IID_IPropertyStore = {886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}
        result = _guid_bytes("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
        expected = bytes([
            0xEB, 0x8E, 0x6D, 0x88,  # Data1 LE
            0xF2, 0x8C,              # Data2 LE
            0x46, 0x44,              # Data3 LE
            0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99,  # Data4
        ])
        self.assertEqual(result, expected)


class TestSetTaskbarProperties(unittest.TestCase):

    def test_does_not_raise_on_invalid_hwnd(self):
        # An invalid HWND should be caught and logged, not raised
        set_taskbar_properties(0, "Test.App", "test.exe", "Test", "test.ico")


class TestAppSetsTaskbarProperties(unittest.TestCase):

    def test_evolver_app_sets_taskbar_pin_properties(self):
        from PyQt6.QtWidgets import QApplication
        from gui.app import EvolverApp, _APP_MODEL_ID

        _app = QApplication.instance() or QApplication([])

        with patch("gui.app.QApplication", return_value=_app), \
             patch("gui.app.set_taskbar_properties") as mock_set:
            app = EvolverApp()

        mock_set.assert_called_once()
        args = mock_set.call_args
        # First arg is HWND (int), second is the app model ID
        self.assertEqual(args[0][1], _APP_MODEL_ID)
        # Display name should be "Evolver"
        self.assertEqual(args[0][3], "Evolver")


if __name__ == "__main__":
    unittest.main()
