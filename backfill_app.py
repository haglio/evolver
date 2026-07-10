#!/usr/bin/env pythonw
"""Metadata backfill tool entry point, launched from Evolver's tray menu.

Plays every clip that still lacks a ``video.action``, shuffled and looping, and
records the act the viewer speaks.  Runs as its own process so an open
microphone or a wedged media backend can never take the tray down with it.
"""

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

import evolver
from backfill.queue import BackfillQueue, unlabeled_videos
from backfill.session import BackfillSession
from backfill.vocabulary import grammar_phrases
from backfill.voice import VoiceListener
from backfill.window import BackfillWindow
from backfill.work import SerialWorker

_TITLE = "Backfill Metadata"
_WINDOW_SIZE = (960, 720)


def main() -> int:
    evolver.setup_logging()
    app = QApplication(sys.argv)

    videos = unlabeled_videos()
    if not videos:
        QMessageBox.information(None, _TITLE, "Every clip already has an action.")
        return 0

    worker = SerialWorker()
    session = BackfillSession(BackfillQueue(videos), worker)

    window = BackfillWindow(session)
    window.resize(*_WINDOW_SIZE)

    listener = VoiceListener(grammar_phrases(), parent=window)
    listener.heard.connect(window.on_phrase)
    listener.start()

    window.show()
    try:
        return app.exec()
    finally:
        listener.stop()
        worker.shutdown()


if __name__ == "__main__":
    sys.exit(main())
