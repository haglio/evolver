"""Tests for backfill_app.main() — the repo's second entry point.

The tray spawns it DETACHED, so a failure in here has no console to land in;
until this module existed, main() and _ready_thumbnails() were entirely
unexercised and backfill_app.py appeared in no coverage report at all.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import backfill_app


class TestMain(unittest.TestCase):
    def _patched(self, videos, **extra):
        patches = dict(
            setup_logging=patch("backfill_app.evolver.setup_logging"),
            qapplication=patch("backfill_app.QApplication"),
            message_box=patch("backfill_app.QMessageBox"),
            unlabeled=patch("backfill_app.unlabeled_videos", return_value=videos),
            thumbnails=patch("backfill_app._ready_thumbnails", return_value={}),
            window=patch("backfill_app.BackfillWindow"),
            listener=patch("backfill_app.VoiceListener"),
            worker=patch("backfill_app.SerialWorker"),
        )
        patches.update(extra)
        return patches

    def test_an_empty_queue_reports_and_exits_zero_without_a_window(self):
        patches = self._patched([])
        with patches["setup_logging"], patches["qapplication"], \
             patches["message_box"] as box, patches["unlabeled"], \
             patches["window"] as window:
            exit_code = backfill_app.main()

        self.assertEqual(exit_code, 0)
        box.information.assert_called_once()
        self.assertIn("already has an action", box.information.call_args[0][2])
        window.assert_not_called()

    def test_a_session_stops_the_listener_and_worker_on_the_way_out(self):
        patches = self._patched([Path("a_topaz.mp4")])
        with patches["setup_logging"], patches["qapplication"] as qapp, \
             patches["message_box"], patches["unlabeled"], patches["thumbnails"], \
             patches["window"] as window, patches["listener"] as listener, \
             patches["worker"] as worker:
            qapp.return_value.exec.return_value = 0
            exit_code = backfill_app.main()

        self.assertEqual(exit_code, 0)
        window.return_value.showMaximized.assert_called_once()
        listener.return_value.start.assert_called_once()
        listener.return_value.heard.connect.assert_called_once_with(
            window.return_value.on_phrase
        )
        listener.return_value.stop.assert_called_once()
        worker.return_value.shutdown.assert_called_once()

    def test_teardown_runs_even_when_the_event_loop_dies(self):
        """The finally clause is what keeps a crashed session from leaving the
        microphone open and the worker thread alive."""
        patches = self._patched([Path("a_topaz.mp4")])
        with patches["setup_logging"], patches["qapplication"] as qapp, \
             patches["message_box"], patches["unlabeled"], patches["thumbnails"], \
             patches["window"], patches["listener"] as listener, \
             patches["worker"] as worker:
            qapp.return_value.exec.side_effect = RuntimeError("backend gone")
            with self.assertRaises(RuntimeError):
                backfill_app.main()

        listener.return_value.stop.assert_called_once()
        worker.return_value.shutdown.assert_called_once()


class TestReadyThumbnails(unittest.TestCase):
    def test_hands_the_window_every_built_thumbnail_as_strings(self):
        built = [("Side Beta", Path("/c/side_beta.jpg")), ("POV Alpha", Path("/c/pov_alpha.jpg"))]
        with patch("backfill_app.build_thumbnails", return_value=built) as build, \
             patch("backfill_app.example_clips", return_value={}) as examples:
            ready = backfill_app._ready_thumbnails()

        self.assertEqual(
            ready,
            {"Side Beta": str(Path("/c/side_beta.jpg")), "POV Alpha": str(Path("/c/pov_alpha.jpg"))},
        )
        build.assert_called_once()
        examples.assert_called_once()


if __name__ == "__main__":
    unittest.main()
