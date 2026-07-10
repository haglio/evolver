#!/usr/bin/env pythonw
"""Metadata backfill tool entry point, launched from Evolver's tray menu.

Plays every clip that still lacks a ``video.action``, shuffled and looping, and
records the act the viewer speaks.  Runs as its own process so an open
microphone or a wedged media backend can never take the tray down with it.
"""

import logging
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import QApplication, QMessageBox

import evolver
from backfill.queue import BackfillQueue, unlabeled_videos
from backfill.session import BackfillSession
from backfill.vocabulary import grammar_phrases
from backfill.voice import VoiceListener
from backfill.window import BackfillWindow

log = logging.getLogger(__name__)

_TITLE = "Backfill Metadata"
_WINDOW_SIZE = (960, 720)


def _run_logging_failures(task: Callable[[], None]) -> None:
    """Run *task*, reporting rather than swallowing whatever it raises.

    The clip has already left the queue by the time this runs, so a failure that
    vanished into a discarded Future would look exactly like a successful label.
    """
    try:
        task()
    except Exception:
        log.exception("Backfill could not record a decision")


def main() -> int:
    evolver.setup_logging()
    app = QApplication(sys.argv)

    videos = unlabeled_videos()
    if not videos:
        QMessageBox.information(None, _TITLE, "Every clip already has an action.")
        return 0

    # One worker, so a rapid-fire run records its decisions in the order they were spoken.
    writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backfill")
    session = BackfillSession(
        BackfillQueue(videos),
        run_in_background=lambda task: writer.submit(_run_logging_failures, task),
    )

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
        writer.shutdown(wait=True)


if __name__ == "__main__":
    sys.exit(main())
