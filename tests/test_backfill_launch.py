"""The tray's Backfill Metadata... item launches the tool as its own process."""
from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

import config
from gui.tray import EvolverTray
from tests.gui_support import build_evolver_app


class TestTrayMenu(unittest.TestCase):
    def test_the_tray_offers_a_backfill_action(self):
        tray = EvolverTray()

        self.assertEqual(tray.backfill_action.text(), "Backfill Metadata...")


class TestLaunch(unittest.TestCase):
    def _app(self):
        return build_evolver_app(self)

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

    def test_review_weird_starts_its_own_process_from_the_tray_and_the_window_alike(self):
        app = self._app()

        with patch("gui.app.subprocess.Popen") as popen:
            app._tray.review_weird_action.trigger()
            app._window.review_weird_action.trigger()

        expected = [sys.executable, str(config.PROJECT_DIR / "review_weird_app.py")]
        self.assertEqual([call.args[0] for call in popen.call_args_list], [expected, expected])
        self.assertTrue(popen.call_args.kwargs["creationflags"] & subprocess.DETACHED_PROCESS)


if __name__ == "__main__":
    unittest.main()
