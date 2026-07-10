"""The backfill tool's window: one looping clip, and how many are left after it."""

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

    Audio is muted: the microphone is open the whole time, and a clip's own
    soundtrack would be one more thing for the recognizer to mishear.
    """

    def __init__(self, session: BackfillSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("Evolver - Backfill Metadata")

        self._video = QVideoWidget()
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video, stretch=1)
        layout.addWidget(self._status)

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
        outcome = self._session.apply(phrase)
        if outcome is None:
            return
        self._play_current(outcome)

    def _play_current(self, outcome: str | None = None) -> None:
        clip = self._session.current
        if clip is None:
            self._release()
            self._status.setText(_DONE)
            return
        # Pointing the player at the next clip is also what makes it let go of the
        # last one, which a background discard is racing to rename.
        self._player.setSource(QUrl.fromLocalFile(str(clip)))
        self._player.play()
        self._status.setText(self._status_text(clip.name, outcome))

    def _release(self) -> None:
        """Stop, and let go of the file the player has open."""
        self._player.stop()
        self._player.setSource(QUrl())

    def _status_text(self, clip_name: str, outcome: str | None) -> str:
        remaining = self._session.remaining
        parts = [f"{remaining} remaining"]
        if outcome is not None:
            parts.append(outcome)
        parts.append(clip_name)
        return "   ·   ".join(parts)

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self._release()
        super().closeEvent(event)
