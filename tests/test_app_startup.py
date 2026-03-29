"""Smoke test: verify the tray app can be constructed without crashing."""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from gui.app import EvolverApp

_app = QApplication.instance() or QApplication([])


class TestAppStartup(unittest.TestCase):

    def test_evolver_app_constructs_without_error(self):
        # Patch QApplication creation since we already have one
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()
        # Tray, window, and scheduler should all exist
        self.assertIsNotNone(app._tray)
        self.assertIsNotNone(app._window)
        self.assertIsNotNone(app._scheduler)


if __name__ == "__main__":
    unittest.main()
