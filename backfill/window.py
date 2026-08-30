"""The backfill tool's window: one looping clip, a live transcript, a clickable grid."""

from __future__ import annotations

from PyQt6.QtCore import QSize, QUrl, Qt
from PyQt6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from backfill.session import BackfillSession
from backfill.vocabulary import Command, control_commands, scoped_grid

_DONE = "Nothing left to label."
_SCROLLBAR_ALLOWANCE = 28
_THUMBNAIL_SIZE = 96
# Reserve the thumbnail's height on every tile up front so every row is the same
# height whether or not its act has an example.
_TILE_HEIGHT = _THUMBNAIL_SIZE + 30


def _aspect_locked_icon(path: str, box: int) -> QIcon:
    """An icon of exactly *box*×*box* holding *path*'s frame at its true aspect.

    The frame is scaled to fit the box keeping its ratio, then centred on a
    transparent square canvas. Because the icon pixmap is already the icon size, no
    platform button style can stretch it to fill — the fix for portrait/landscape
    frames coming out squished to square on native Windows.
    """
    source = QPixmap(path)
    if source.isNull():
        return QIcon()
    scaled = source.scaled(
        box, box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    canvas = QPixmap(box, box)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap((box - scaled.width()) // 2, (box - scaled.height()) // 2, scaled)
    painter.end()
    return QIcon(canvas)


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
    microphone never leaves the tool unusable. Each act tile carries an example
    frame — passed in ready at construction, already cached — so the panel opens
    as a gallery with nothing to load.

    Audio is muted: the microphone is open the whole time, and a clip's own
    soundtrack would be one more thing for the recognizer to mishear.
    """

    def __init__(self, session: BackfillSession, thumbnails: dict[str, str] | None = None) -> None:
        super().__init__()
        self._session = session
        self._tiles: dict[str, QToolButton] = {}
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

        for action, path in (thumbnails or {}).items():
            self.set_thumbnail(action, path)

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

    def _command_tile(self, command: Command) -> QToolButton:
        """A button that hands *command*'s phrase to the same slot the mic feeds.

        Text-under-icon with the icon space reserved from the start, so an example
        thumbnail arriving later fills that space instead of reflowing the grid.
        """
        tile = QToolButton()
        tile.setText(command.label)
        tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tile.setIconSize(QSize(_THUMBNAIL_SIZE, _THUMBNAIL_SIZE))
        tile.setMinimumHeight(_TILE_HEIGHT)
        tile.setToolTip(f'Say "{command.phrase}"')
        # Never take keyboard focus: the space bar must not re-fire the last tile,
        # and Esc must keep closing the window rather than being swallowed here.
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _checked=False, phrase=command.phrase: self.on_phrase(phrase))
        # One index, reachable by either name a caller has: the spoken phrase,
        # and the act label lower-cased so an example clip stored under the
        # library's older casing ("Pov Alpha") still lights the tile the
        # vocabulary now writes ("POV Alpha"). The two agree for most commands
        # and differ where the phrase is shorter than the label ("side dance"
        # records "Side Dancing").
        self._tiles[command.phrase] = tile
        self._tiles[command.label.lower()] = tile
        return tile

    # The window's read surface: what the three lines say and which tile a
    # phrase or an action owns. One-liners over the same widgets, so the
    # internals -- label fields, the media backend, how tiles are keyed -- can
    # move without breaking every assertion made about the window (31 reads of
    # six private attributes before these existed).

    def status_text(self) -> str:
        return self._status.text()

    def hearing_text(self) -> str:
        return self._hearing.text()

    def last_text(self) -> str:
        return self._last.text()

    def tile_for(self, key: str) -> QToolButton | None:
        """The tile for a spoken *key* -- a command phrase, or an act label in
        any casing."""
        return self._tiles.get(key) or self._tiles.get(key.lower())

    def set_thumbnail(self, action: str, path: str) -> None:
        """Put *action*'s example frame on its tile, aspect-locked so it never stretches."""
        tile = self._tiles.get(action.lower())
        if tile is None or not path:
            return
        icon = _aspect_locked_icon(path, _THUMBNAIL_SIZE)
        if not icon.isNull():
            tile.setIcon(icon)

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
