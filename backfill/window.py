"""The backfill tool's window: one looping clip, how many are left, and what you last said."""

from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from backfill.session import BackfillSession

_DONE = "Nothing left to label."


class BackfillWindow(QWidget):
    """Loops the clip awaiting an action, and moves on the moment one is spoken.

    Two lines beneath the video: what is on screen now, and what the last thing you
    said did — naming its own clip, which by then is not the one you are watching.

    Audio is muted: the microphone is open the whole time, and a clip's own
    soundtrack would be one more thing for the recognizer to mishear.
    """

    def __init__(self, session: BackfillSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("Evolver - Backfill Metadata")

        self._video = QVideoWidget()
        self._status = QLabel()
        self._last = QLabel()
        for label in (self._status, self._last):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video, stretch=1)
        layout.addWidget(self._status)
        layout.addWidget(self._last)

        self._audio = QAudioOutput()
        self._audio.setMuted(True)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        self._play_current()

    def on_phrase(self, phrase: str) -> None:
        """React to a phrase the listener heard."""
        was_playing = self._session.current
        note = self._session.apply(phrase)
        if note is None:
            return
        # A skip with one clip left, and an undo with nothing to undo, both leave the
        # same clip on screen — reloading it would restart it from the top for nothing.
        if self._session.current != was_playing:
            self._play_current()
        else:
            self._refresh_status()
        self._last.setText(f"Last: {note}")

    def _play_current(self) -> None:
        clip = self._session.current
        if clip is None:
            self._release()
        else:
            # Pointing the player at the next clip is also what makes it let go of the
            # last one, which a background discard is racing to rename.
            self._player.setSource(QUrl.fromLocalFile(str(clip)))
            self._player.play()
        self._refresh_status()

    def _refresh_status(self) -> None:
        clip = self._session.current
        if clip is None:
            self._status.setText(_DONE)
        else:
            self._status.setText(f"{self._session.remaining} remaining   ·   {clip.name}")

    def _release(self) -> None:
        """Stop, and let go of the file the player has open."""
        self._player.stop()
        self._player.setSource(QUrl())

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self._release()
        super().closeEvent(event)
