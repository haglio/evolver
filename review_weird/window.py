from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import TEXT_MUTED, TEXT_SECONDARY
from shared_ui.icons import glyph_icon
from shared_ui.spacing import MARGIN_STANDARD

import config
from util import weird_piles
from util.player_readout import silence_the_ffmpeg_format_dump

LOOK_AGAIN_SECONDS = 2.0
_ICON_COLOR = TEXT_SECONDARY.name()
_HINT = ("Restore puts a video back in the folder it was marked weird in. Delete Permanently deletes it, "
         "along with the copy it was upscaled from, its metadata and its funscript. "
         "Ctrl or Shift picks several.")
_NOWHERE = "Nothing says which folder it was marked weird in, so it can't be restored"


class ReviewWeirdWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Evolver - Review Weird")
        self.resize(1200, 720)

        self.heading = QLabel()
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        hint = QLabel(_HINT)
        hint.setStyleSheet(f"color: {TEXT_MUTED.name()}")
        hint.setWordWrap(True)

        self.videos = QTreeWidget()
        self.videos.setHeaderLabels(["Video", "Restores to"])
        self.videos.setRootIsDecorated(False)
        self.videos.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.videos.currentItemChanged.connect(self._play)
        self.videos.itemSelectionChanged.connect(self._offer_what_can_be_done)

        screen = QVideoWidget()
        silence_the_ffmpeg_format_dump()
        self._sound = QAudioOutput()
        self._sound.setMuted(True)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self._sound)
        self.player.setVideoOutput(screen)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)

        self.restore_button = QPushButton(glyph_icon("undo_arrow", color=_ICON_COLOR), "Restore")
        self.restore_button.clicked.connect(self._restore)
        self.delete_button = QPushButton(glyph_icon("trash", color=_ICON_COLOR), "Delete Permanently")
        self.delete_button.clicked.connect(self._delete_permanently)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self, self._delete_permanently)

        self.watch = QTimer(self)
        self.watch.setInterval(int(LOOK_AGAIN_SECONDS * 1000))
        self.watch.timeout.connect(self._look_again)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD)
        layout.addWidget(self.heading)
        layout.addWidget(hint)
        layout.addWidget(_side_by_side(self.videos, _above(screen, self.restore_button,
                                                           self.delete_button)), stretch=1)

        self._show(weird_piles.marked_weird(), row=0)

    def _show(self, marked: list[weird_piles.MarkedWeird], row: int,
              current: Path | None = None, picked: frozenset[Path] = frozenset()) -> None:
        self._marked = marked
        self.heading.setText(_counted(len(marked)))
        self.videos.clear()
        for each in marked:
            item = QTreeWidgetItem([each.video.name, _folder(each.restores_to)])
            item.setData(0, Qt.ItemDataRole.UserRole, each)
            item.setToolTip(0, str(each.video))
            item.setToolTip(1, _NOWHERE if each.restores_to is None else str(each.restores_to))
            self.videos.addTopLevelItem(item)
        at = next((at for at, each in enumerate(marked) if each.video == current),
                  min(row, len(marked) - 1))
        self.videos.setCurrentItem(self.videos.topLevelItem(at))
        for at, each in enumerate(marked):
            if each.video in picked:
                self.videos.topLevelItem(at).setSelected(True)
        self._offer_what_can_be_done()

    def _play(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        source = QUrl.fromLocalFile(str(_marked(item).video))
        if self.player.source() != source:
            self.player.setSource(source)
            self.player.play()

    def _look_again(self) -> None:
        if weird_piles.videos_marked_weird() != [each.video for each in self._marked]:
            current = self.videos.currentItem()
            self._show(weird_piles.marked_weird(), self.videos.indexOfTopLevelItem(current),
                       current=_marked(current).video if current is not None else None,
                       picked=frozenset(each.video for each in self._chosen()))

    def _restore(self) -> None:
        self._settle(weird_piles.restore)

    def _delete_permanently(self) -> None:
        if self._chosen():
            self._settle(weird_piles.delete_permanently)

    def _settle(self, verdict) -> None:
        row = self.videos.indexOfTopLevelItem(self.videos.currentItem())
        chosen = self._chosen()
        self._let_go()
        for marked in chosen:
            try:
                verdict(marked)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Review Weird", f"{marked.video.name}: {error}")
        self._show(weird_piles.marked_weird(), row)

    def _chosen(self) -> list[weird_piles.MarkedWeird]:
        return [_marked(item) for item in self.videos.selectedItems()]

    def _offer_what_can_be_done(self) -> None:
        chosen = self._chosen()
        self.restore_button.setEnabled(
            bool(chosen) and all(marked.restores_to is not None for marked in chosen))
        self.delete_button.setEnabled(bool(chosen))

    def _let_go(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())

    def showEvent(self, event):
        super().showEvent(event)
        self.watch.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.watch.stop()


def _side_by_side(left: QWidget, right: QWidget) -> QSplitter:
    sides = QSplitter(Qt.Orientation.Horizontal)
    sides.addWidget(left)
    sides.addWidget(right)
    sides.setSizes([450, 750])
    return sides


def _above(screen: QWidget, *buttons: QPushButton) -> QWidget:
    row = QHBoxLayout()
    for button in buttons:
        row.addWidget(button)
    stack = QWidget()
    layout = QVBoxLayout(stack)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(screen, stretch=1)
    layout.addLayout(row)
    return stack


def _marked(item: QTreeWidgetItem) -> weird_piles.MarkedWeird:
    return item.data(0, Qt.ItemDataRole.UserRole)


def _counted(videos: int) -> str:
    if not videos:
        return "Nothing is marked weird"
    return f"{videos} video{'' if videos == 1 else 's'} marked weird"


def _folder(restores_to: Path | None) -> str:
    if restores_to is None:
        return "can't tell"
    return str(restores_to.parent.relative_to(config.VIDEO_SEARCH_ROOT))
