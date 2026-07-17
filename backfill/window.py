"""The backfill tool's window: one looping clip, a live transcript, a clickable grid."""

from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backfill.session import BackfillSession
from backfill.vocabulary import Command, control_commands, scoped_grid

_DONE = "Nothing left to label."
_SCROLLBAR_ALLOWANCE = 28


class BackfillWindow(QWidget):
    """Loops the clip awaiting an action, and moves on the moment one is chosen.

    The clip plays on the left under three lines: what is on screen now, what the
    recognizer is hearing this moment, and what the last thing you said did — the
    last naming its own clip, which by then is not the one you are watching.

    The live "hearing" line is the answer to "is it even listening?": it fills in
    as on-script words are recognized and stays blank when what you said is not a
    command, so a phrase that never lands is visible rather than a silent nothing.

    A panel of every command sits on the right, one tile per possibility grouped
    the way the vocabulary is — every act as a grid of Side/POV columns, then the
    controls. A tile is both the reference (what can I say?) and a fallback:
    clicking it drives the exact path a spoken phrase would, so a wedged
    microphone never leaves the tool unusable.

    Audio is muted: the microphone is open the whole time, and a clip's own
    soundtrack would be one more thing for the recognizer to mishear.
    """

    def __init__(self, session: BackfillSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._command_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("Evolver - Backfill Metadata")

        self._video = QVideoWidget()
        self._status = QLabel()
        self._hearing = QLabel()
        self._last = QLabel()
        for label in (self._status, self._hearing, self._last):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stage = QVBoxLayout()
        stage.setContentsMargins(0, 0, 0, 0)
        stage.addWidget(self._video, stretch=1)
        stage.addWidget(self._status)
        stage.addWidget(self._hearing)
        stage.addWidget(self._last)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(stage, stretch=1)
        layout.addWidget(self._build_command_panel())

        self._audio = QAudioOutput()
        self._audio.setMuted(True)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        self._play_current()

    def _build_command_panel(self) -> QWidget:
        """The scrollable right-hand reference: every command as a clickable tile."""
        contents = QVBoxLayout()

        acts = QGridLayout()
        for row, commands in enumerate(scoped_grid()):
            for column, command in enumerate(commands):
                acts.addWidget(self._command_tile(command), row, column)
        contents.addLayout(acts)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        contents.addWidget(divider)

        controls = QHBoxLayout()
        for command in control_commands():
            controls.addWidget(self._command_tile(command))
        contents.addLayout(controls)
        contents.addStretch(1)

        inner = QWidget()
        inner.setLayout(contents)
        panel = QScrollArea()
        panel.setWidget(inner)
        panel.setWidgetResizable(True)
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Size to the grid's own width (the Side/POV columns at this machine's
        # font) rather than a hardcoded guess, plus room for the vertical
        # scrollbar, so no column is ever clipped off the right edge.
        panel.setFixedWidth(inner.sizeHint().width() + _SCROLLBAR_ALLOWANCE)
        return panel

    def _command_tile(self, command: Command) -> QPushButton:
        """A button that hands *command*'s phrase to the same slot the mic feeds."""
        tile = QPushButton(command.label)
        tile.setToolTip(f'Say "{command.phrase}"')
        # Never take keyboard focus: the space bar must not re-fire the last tile,
        # and Esc must keep closing the window rather than being swallowed here.
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _checked=False, phrase=command.phrase: self.on_phrase(phrase))
        self._command_buttons[command.phrase] = tile
        return tile

    def on_hearing(self, text: str) -> None:
        """Show the recognizer's live guess, or clear the line once it settles."""
        self._hearing.setText(f"Hearing: {text}" if text else "")

    def on_phrase(self, phrase: str) -> None:
        """React to a phrase — spoken or clicked."""
        # The phrase settled, so the live guess that led to it is spent.
        self._hearing.setText("")
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
