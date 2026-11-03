from __future__ import annotations

import sys

from PyQt6.QtWidgets import QMessageBox
from shared_ui.application import application

import evolver
from backfill.queue import BackfillQueue, ScannedVideo, library_scan, unlabeled_videos
from backfill.session import BackfillSession
from backfill.thumbnails import (
    build_thumbnails,
    example_videos,
    extract_frame,
    thumbnail_cache_path,
)
from backfill.vocabulary import Vocabulary, load_vocabulary
from backfill.voice import VoiceListener
from backfill.window import BackfillWindow
from backfill.work import SerialWorker
from gui import process_identity

_TITLE = "Backfill Metadata"


def _ready_thumbnails(vocabulary: Vocabulary, scan: list[ScannedVideo]) -> dict[str, str]:
    return {
        action: str(path)
        for action, path in build_thumbnails(
            example_videos(vocabulary, scan), extract_frame, thumbnail_cache_path)
    }


def main() -> int:
    evolver.setup_logging()
    with application(sys.argv) as app:
        return _label_the_unlabeled(app)


def _label_the_unlabeled(app) -> int:
    process_identity.claim(app)

    scan = library_scan()
    videos = unlabeled_videos(scan)
    if not videos:
        QMessageBox.information(None, _TITLE, "Every video already has an action.")
        return 0

    worker = SerialWorker()
    vocabulary = load_vocabulary()
    session = BackfillSession(BackfillQueue(videos), worker, vocabulary)

    window = BackfillWindow(session, vocabulary, thumbnails=_ready_thumbnails(vocabulary, scan))

    listener = VoiceListener(vocabulary.grammar_phrases(), parent=window,
                             never_repaired=vocabulary.discarding_phrases())
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
