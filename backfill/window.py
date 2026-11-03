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
_BUTTON_HEIGHT = _THUMBNAIL_SIZE + 30


def _aspect_locked_icon(path: str, side: int) -> QIcon:
    # The pixmap is already the icon size, so no native Windows button style stretches it to fill.
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
        panel.setFixedWidth(inner.sizeHint().width() + _SCROLLBAR_ALLOWANCE)
        return panel

    def _command_button(self, command: Command) -> QToolButton:
        button = QToolButton()
        button.setText(command.label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(_THUMBNAIL_SIZE, _THUMBNAIL_SIZE))
        button.setMinimumHeight(_BUTTON_HEIGHT)
        button.setToolTip(f'Say "{command.phrase}"')
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _checked=False, phrase=command.phrase: self.on_phrase(phrase))
        self._buttons[command.phrase] = button
        return button

    def status_text(self) -> str:
        return self._status.text()

    def hearing_text(self) -> str:
        return self._hearing.text()

    def last_text(self) -> str:
        return self._last.text()

    def button_for(self, key: str) -> QToolButton | None:
        button = self._buttons.get(key)
        return button if button is not None else self._button_labelled(key)

    def _button_labelled(self, label: str) -> QToolButton | None:
        wanted = label.lower()
        return next((button for button in self._buttons.values() if button.text().lower() == wanted), None)

    def set_thumbnail(self, label: str, path: str) -> None:
        button = self._button_labelled(label)
        if button is None or not path:
            return
        icon = _aspect_locked_icon(path, _THUMBNAIL_SIZE)
        if not icon.isNull():
            button.setIcon(icon)

    def on_hearing(self, text: str) -> None:
        self._hearing.setText(f"Hearing: {text}" if text else "")

    def on_voice_failed(self, detail: str) -> None:
        self._hearing.setText(f"Speech recognition stopped: {detail}")

    def on_phrase(self, phrase: str) -> None:
        self._hearing.setText("")
        was_playing = self._session.current
        note = self._session.apply(phrase)
        if note is None:
            return
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
            self._preview.show(video)
        self._refresh_status()

    def _refresh_status(self) -> None:
        video = self._session.current
        if video is None:
            self._status.setText(_DONE)
        else:
            self._status.setText(f"{self._session.remaining} remaining   ·   {video.name}")

    def _release(self) -> None:
        self._preview.let_go()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self._release()
        super().closeEvent(event)
