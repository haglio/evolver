#!/usr/bin/env pythonw
"""Metadata backfill tool entry point, launched from Evolver's tray menu.

Plays every clip that still lacks a ``video.action``, looping in a stable order,
and records the act the viewer speaks.  Runs as its own process so an open
microphone or a wedged media backend can never take the tray down with it.
"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

import evolver
from backfill.queue import BackfillQueue, ScannedClip, library_scan, unlabeled_clips
from backfill.session import BackfillSession
from backfill.thumbnails import build_thumbnails, example_clips, extract_frame, thumbnail_cache_path
from backfill.vocabulary import Vocabulary, grammar_phrases, load_vocabulary
from backfill.voice import VoiceListener
from backfill.window import BackfillWindow
from backfill.work import SerialWorker

_TITLE = "Backfill Metadata"


def _ready_thumbnails(vocabulary: Vocabulary, scan: list[ScannedClip]) -> dict[str, str]:
    """Every tile's cached thumbnail, ready to hand the window at construction.

    Cached frames are read straight back; only an act whose frame was never made
    (a new curated example) is extracted here, so a warmed cache opens instantly.
    """
    return {
        action: str(path)
        for action, path in build_thumbnails(
            example_clips(vocabulary, scan), extract_frame, thumbnail_cache_path)
    }


def main() -> int:
    evolver.setup_logging()
    app = QApplication(sys.argv)

    # One walk of the library, one parse of each sidecar: the work queue and
    # the example clips are two projections of it (util_backfill/design/005).
    scan = library_scan()
    clips = unlabeled_clips(scan)
    if not clips:
        QMessageBox.information(None, _TITLE, "Every clip already has an action.")
        return 0

    worker = SerialWorker()
    vocabulary = load_vocabulary()
    session = BackfillSession(BackfillQueue(clips), worker, vocabulary)

    window = BackfillWindow(session, vocabulary, thumbnails=_ready_thumbnails(vocabulary, scan))

    listener = VoiceListener(grammar_phrases(), parent=window)
    listener.heard.connect(window.on_phrase)
    listener.hearing.connect(window.on_hearing)
    listener.failed.connect(window.on_voice_failed)
    listener.start()

    window.showMaximized()
    try:
        return app.exec()
    finally:
        listener.stop()
        worker.shutdown()


if __name__ == "__main__":
    sys.exit(main())
