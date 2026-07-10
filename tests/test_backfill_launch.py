"""The tray's Backfill Metadata... item launches the tool as its own process."""

import subprocess
import sys
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

import config
from gui.app import EvolverApp
from gui.tray import EvolverTray

_app = QApplication.instance() or QApplication([])


class TestTrayMenu(unittest.TestCase):
    def test_the_tray_offers_a_backfill_action(self):
        tray = EvolverTray()

        self.assertEqual(tray.backfill_action.text(), "Backfill Metadata...")


class TestLaunch(unittest.TestCase):
    def _app(self):
        with patch("gui.app.QApplication", return_value=_app):
            return EvolverApp()

    def test_triggering_the_action_spawns_the_backfill_process(self):
        app = self._app()

        with patch("gui.app.subprocess.Popen") as popen:
            app._tray.backfill_action.trigger()

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args[0][0],
            [sys.executable, str(config.PROJECT_DIR / "backfill_app.py")],
        )

    def test_the_backfill_process_outlives_the_tray_that_spawned_it(self):
        app = self._app()

        with patch("gui.app.subprocess.Popen") as popen:
            app._tray.backfill_action.trigger()

        creationflags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(creationflags & subprocess.DETACHED_PROCESS)


if __name__ == "__main__":
    unittest.main()
