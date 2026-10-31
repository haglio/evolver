"""A video shown over and over, with no sound, until the window lets it go."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

from util.player_readout import silence_the_ffmpeg_format_dump


class LoopingPreview:
    def __init__(self, screen: QVideoWidget) -> None:
        silence_the_ffmpeg_format_dump()
        self.player = QMediaPlayer()
        self.player.setVideoOutput(screen)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)

    def is_showing(self, video: Path) -> bool:
        return self.player.source() == QUrl.fromLocalFile(str(video))

    def show(self, video: Path) -> None:
        self.player.setSource(QUrl.fromLocalFile(str(video)))
        self.player.play()

    def let_go(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
