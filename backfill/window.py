"""The backfill tool's window: one looping video, a live transcript, a clickable grid."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
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
from backfill.vocabulary import Command, Vocabulary
from util.looping_preview import LoopingPreview

_DONE = "Nothing left to label."
_SCROLLBAR_ALLOWANCE = 28
_THUMBNAIL_SIZE = 96
# Reserve the thumbnail's height on every button up front so every row is the same
# height whether or not its act has an example.
_BUTTON_HEIGHT = _THUMBNAIL_SIZE + 30


def _aspect_locked_icon(path: str, side: int) -> QIcon:
    """An icon of exactly *side*×*side* holding *path*'s frame at its true aspect.

    The frame is scaled to fit the square keeping its ratio, then centered on a
    transparent square canvas. Because the icon pixmap is already the icon size, no
    platform button style can stretch it to fill — the fix for portrait/landscape
    frames coming out squished to square on native Windows.
    """
    source = QPixmap(path)
    if source.isNull():
        return QIcon()
    scaled = source.scaled(
        side, side, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(side, side)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap((side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled)
    painter.end()
    return QIcon(canvas)


class BackfillWindow(QWidget):
    """Loops the video awaiting an action, and moves on the moment one is chosen.

    The video plays on the left under three lines: what is on screen now, what the
    recognizer is hearing this moment, and what the last thing you said did — the
    last naming its own video, which by then is not the one you are watching.

    The live "hearing" line is the answer to "is it even listening?": it fills in
    as on-script words are recognized and stays blank when what you said is not a
    command, so a phrase that never lands is visible rather than a silent nothing.

    A panel of every command sits on the right, one button per possibility grouped
    the way the vocabulary is — every act as a row with a column per camera
    word, then the controls. A button is both the reference (what can I say?) and a fallback:
    clicking it drives the exact path a spoken phrase would, so a wedged
    microphone never leaves the tool unusable. Each act button carries an example
    frame — passed in ready at construction, already cached — so the panel opens
    as a gallery with nothing to load.

    The video plays with no sound output: the microphone is open the whole time,
    and a video's own soundtrack would be one more thing for the recognizer to mishear.
    """

    def __init__(
        self, session: BackfillSession, vocabulary: Vocabulary, thumbnails: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._buttons: dict[str, QToolButton] = {}
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
        layout.addWidget(self._build_button_grid(vocabulary))

        for label, path in (thumbnails or {}).items():
            self.set_thumbnail(label, path)

        self._preview = LoopingPreview(self._video)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        self._play_current()

    def _build_button_grid(self, vocabulary: Vocabulary) -> QWidget:
        """The scrollable right-hand reference: every command as a clickable button."""
        contents = QVBoxLayout()

        acts = QGridLayout()
        for row, commands in enumerate(vocabulary.scoped_grid()):
            for column, command in enumerate(commands):
                acts.addWidget(self._command_button(command), row, column)
        contents.addLayout(acts)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        contents.addWidget(divider)

        controls = QHBoxLayout()
        for command in vocabulary.control_commands():
            controls.addWidget(self._command_button(command))
        contents.addLayout(controls)
        contents.addStretch(1)

        inner = QWidget()
        inner.setLayout(contents)
        panel = QScrollArea()
        panel.setWidget(inner)
        panel.setWidgetResizable(True)
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Size to the grid's own width (the camera columns at this computer's
        # font) rather than a hardcoded guess, plus room for the vertical
        # scrollbar, so no column is ever videoped off the right edge.
        panel.setFixedWidth(inner.sizeHint().width() + _SCROLLBAR_ALLOWANCE)
        return panel

    def _command_button(self, command: Command) -> QToolButton:
        """A button that hands *command*'s phrase to the same slot the mic feeds.

        Text-under-icon with the icon space reserved from the start, so an example
        thumbnail arriving later fills that space instead of reflowing the grid.
        """
        button = QToolButton()
        button.setText(command.label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(_THUMBNAIL_SIZE, _THUMBNAIL_SIZE))
        button.setMinimumHeight(_BUTTON_HEIGHT)
        button.setToolTip(f'Say "{command.phrase}"')
        # Never take keyboard focus: the space bar must not re-fire the last button,
        # and Esc must keep closing the window rather than being swallowed here.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _checked=False, phrase=command.phrase: self.on_phrase(phrase))
        # Keyed by the spoken phrase and nothing else. A label is not a second
        # key here: one command's phrase can equal another's label, and a dict
        # holding both would hand the second button the first one's name.
        self._buttons[command.phrase] = button
        return button

    # The window's read surface: what the three lines say and which button a
    # phrase or an action owns. One-liners over the same widgets, so the
    # internals -- label fields, the media backend, how buttons are keyed -- can
    # move without breaking every assertion made about the window (31 reads of
    # six private attributes before these existed).

    def status_text(self) -> str:
        return self._status.text()

    def hearing_text(self) -> str:
        return self._hearing.text()

    def last_text(self) -> str:
        return self._last.text()

    def button_for(self, key: str) -> QToolButton | None:
        """The button for a spoken *key* -- a command phrase, or an act label in
        any casing."""
        button = self._buttons.get(key)
        return button if button is not None else self._button_labelled(key)

    def _button_labelled(self, label: str) -> QToolButton | None:
        """The button whose face reads *label*, in any casing.

        Read off the buttons themselves rather than a second index: the label
        is already the button's text, and case-folding bridges the library's
        older action casing (an initialism title-cased, "Xyz Alpha", against
        the "XYZ Alpha" the vocabulary writes today).
        """
        wanted = label.lower()
        return next((button for button in self._buttons.values() if button.text().lower() == wanted), None)

    def set_thumbnail(self, label: str, path: str) -> None:
        """Put *label*'s example frame on its button, aspect-locked so it never stretches."""
        button = self._button_labelled(label)
        if button is None or not path:
            return
        icon = _aspect_locked_icon(path, _THUMBNAIL_SIZE)
        if not icon.isNull():
            button.setIcon(icon)

    def on_hearing(self, text: str) -> None:
        """Show the recognizer's live guess, or clear the line once it settles."""
        self._hearing.setText(f"Hearing: {text}" if text else "")

    def on_voice_failed(self, detail: str) -> None:
        """Say the microphone path has gone, where the live guess used to be.

        The buttons still work -- they are clickable -- so the window does not
        close or disable anything. What it must not do is go on looking like it
        is listening.
        """
        self._hearing.setText(f"Speech recognition stopped: {detail}")

    def on_phrase(self, phrase: str) -> None:
        """React to a phrase — spoken or clicked."""
        # The phrase settled, so the live guess that led to it is spent.
        self._hearing.setText("")
        was_playing = self._session.current
        note = self._session.apply(phrase)
        if note is None:
            return
        # A skip with one video left, and an undo with nothing to undo, both leave the
        # same video on screen — reloading it would restart it from the top for nothing.
        if self._session.current != was_playing:
            self._play_current()
        else:
            self._refresh_status()
        self._last.setText(f"Last: {note}")

    def _play_current(self) -> None:
        video = self._session.current
        if video is None:
            self._release()
        else:
            # Pointing the player at the next video is also what makes it let go of the
            # last one, which a background discard is racing to rename.
            self._preview.show(video)
        self._refresh_status()

    def _refresh_status(self) -> None:
        video = self._session.current
        if video is None:
            self._status.setText(_DONE)
        else:
            self._status.setText(f"{self._session.remaining} remaining   ·   {video.name}")

    def _release(self) -> None:
        """Stop, and let go of the file the player has open."""
        self._preview.let_go()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self._release()
        super().closeEvent(event)
