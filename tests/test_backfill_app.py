"""Tests for backfill_app.main() — the repo's second entry point.

The tray spawns it DETACHED, so a failure in here has no console to land in;
until this module existed, main() and _ready_thumbnails() were entirely
unexercised and backfill_app.py appeared in no coverage report at all.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import ANY, patch

import backfill_app
from tests.product_sources import PROJECT_ROOT


class TestMain(unittest.TestCase):
    def _patched(self, videos, **extra):
        patches = dict(
            setup_logging=patch("backfill_app.evolver.setup_logging"),
            qapplication=patch("backfill_app.QApplication"),
            alert=patch("backfill_app.QMessageBox"),
            unlabeled=patch("backfill_app.unlabeled_clips", return_value=videos),
            thumbnails=patch("backfill_app._ready_thumbnails", return_value={}),
            window=patch("backfill_app.BackfillWindow"),
            listener=patch("backfill_app.VoiceListener"),
            worker=patch("backfill_app.SerialWorker"),
            vocabulary=patch("backfill_app.load_vocabulary"),
            session=patch("backfill_app.BackfillSession"),
        )
        patches.update(extra)
        return patches

    def _run_main(self, videos=(Path("a_topaz.mp4"),)):
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(p) for name, p in self._patched(list(videos)).items()}
            mocks["qapplication"].return_value.exec.return_value = 0
            backfill_app.main()
        return mocks

    def test_an_empty_queue_reports_and_exits_zero_without_a_window(self):
        patches = self._patched([])
        with patches["setup_logging"], patches["qapplication"], \
             patches["alert"] as alert, patches["unlabeled"], \
             patches["window"] as window:
            exit_code = backfill_app.main()

        self.assertEqual(exit_code, 0)
        alert.information.assert_called_once()
        self.assertIn("already has an action", alert.information.call_args[0][2])
        window.assert_not_called()

    def test_a_session_stops_the_listener_and_worker_on_the_way_out(self):
        patches = self._patched([Path("a_topaz.mp4")])
        with patches["setup_logging"], patches["qapplication"] as qapp, \
             patches["alert"], patches["unlabeled"], patches["thumbnails"], \
             patches["window"] as window, patches["listener"] as listener, \
             patches["worker"] as worker, patches["vocabulary"]:
            qapp.return_value.exec.return_value = 0
            exit_code = backfill_app.main()

        self.assertEqual(exit_code, 0)
        window.return_value.showMaximized.assert_called_once()
        listener.return_value.start.assert_called_once()
        listener.return_value.heard.connect.assert_called_once_with(
            window.return_value.on_phrase
        )
        # A recognizer that dies has to reach the window, or the grid goes on
        # looking like it is listening.
        listener.return_value.failed.connect.assert_called_once_with(
            window.return_value.on_voice_failed
        )
        listener.return_value.stop.assert_called_once()
        worker.return_value.shutdown.assert_called_once()

    def test_teardown_runs_even_when_the_event_loop_dies(self):
        """The finally clause is what keeps a crashed session from leaving the
        microphone open and the worker thread alive."""
        patches = self._patched([Path("a_topaz.mp4")])
        with patches["setup_logging"], patches["qapplication"] as qapp, \
             patches["alert"], patches["unlabeled"], patches["thumbnails"], \
             patches["window"], patches["listener"] as listener, \
             patches["worker"] as worker, patches["vocabulary"]:
            qapp.return_value.exec.side_effect = RuntimeError("backend gone")
            with self.assertRaises(RuntimeError):
                backfill_app.main()

        listener.return_value.stop.assert_called_once()
        worker.return_value.shutdown.assert_called_once()

    def test_the_session_is_handed_the_vocabulary_main_loads(self):
        mocks = self._run_main()

        mocks["session"].assert_called_once_with(ANY, ANY, mocks["vocabulary"].return_value)

    def test_the_window_is_handed_the_vocabulary_main_loads(self):
        mocks = self._run_main()

        mocks["window"].assert_called_once_with(
            mocks["session"].return_value, mocks["vocabulary"].return_value, thumbnails=ANY)

    def test_the_example_clips_are_picked_for_the_vocabulary_main_loads(self):
        mocks = self._run_main()

        mocks["thumbnails"].assert_called_once_with(mocks["vocabulary"].return_value, ANY)

    def test_the_recognizer_listens_for_the_phrases_of_the_vocabulary_main_loads(self):
        mocks = self._run_main()

        mocks["listener"].assert_called_once_with(
            mocks["vocabulary"].return_value.grammar_phrases.return_value, parent=ANY,
            never_repaired=ANY)

    def test_a_phrase_that_discards_the_clip_is_never_repaired_from_a_near_miss(self):
        mocks = self._run_main()

        self.assertIs(
            mocks["listener"].call_args.kwargs["never_repaired"],
            mocks["vocabulary"].return_value.discarding_phrases.return_value)


class TestReadyThumbnails(unittest.TestCase):
    def test_hands_the_window_every_built_thumbnail_as_strings(self):
        built = [("Side Beta", Path("/c/side_beta.jpg")), ("XYZ Alpha", Path("/c/xyz_alpha.jpg"))]
        vocabulary, scan = object(), []
        with patch("backfill_app.build_thumbnails", return_value=built) as build, \
             patch("backfill_app.example_clips", return_value={}) as examples:
            ready = backfill_app._ready_thumbnails(vocabulary, scan)

        self.assertEqual(
            ready,
            {"Side Beta": str(Path("/c/side_beta.jpg")), "XYZ Alpha": str(Path("/c/xyz_alpha.jpg"))},
        )
        build.assert_called_once()
        examples.assert_called_once_with(vocabulary, scan)

    def test_the_library_is_walked_once_for_both_of_startup_s_questions(self):
        """The work queue and the example clips are two projections of one
        scan. Two walks and two sidecar parses is a tray-launched tool sitting
        with no window on screen for twice as long as it needs to."""
        with patch("backfill_app.library_scan", return_value=[]) as scan, \
                patch("backfill_app.unlabeled_clips", return_value=[]), \
                patch("backfill_app.QApplication"), \
                patch("backfill_app.QMessageBox"), \
                patch("backfill_app.evolver.setup_logging"):
            backfill_app.main()

        scan.assert_called_once_with()


# In a fresh interpreter, because an import-time read is a cost this process has
# already paid. Config reads the overlay as it is imported, so it is imported
# before the count starts, and what is counted is the tool's own.
_OVERLAY_READS = """
import json
from pathlib import Path
import content_overlay
content_overlay.LOCAL_CONTENT = content_overlay.EXAMPLE_CONTENT
import config

reads = []
_read_text = Path.read_text
Path.read_text = lambda self, *a, **k: (reads.append(self.name), _read_text(self, *a, **k))[1]
import backfill_app
at_import = [name for name in reads if name.startswith("content.")]
reads.clear()
backfill_app.load_vocabulary()
when_asked = [name for name in reads if name.startswith("content.")]
print(json.dumps({"at_import": at_import, "when_asked": when_asked}))
"""


class TestTheActTableIsReadWhenMainAsksForIt(unittest.TestCase):
    def test_importing_the_tool_reads_no_overlay_and_loading_its_vocabulary_reads_one(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", _OVERLAY_READS],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {"at_import": [], "when_asked": ["content.example.json"]},
        )


if __name__ == "__main__":
    unittest.main()
