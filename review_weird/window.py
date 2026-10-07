from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
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

_ICON_COLOR = TEXT_SECONDARY.name()
_HINT = ("Put Back returns a video to the folder it was marked weird in. Delete for Good deletes it, "
         "along with the copy it was upscaled from, its metadata and its funscript. "
         "Ctrl or Shift picks several.")
_NOWHERE = "Nothing says which folder it was marked weird in, so it can't be put back"


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
        self.videos.setHeaderLabels(["Video", "Goes back to"])
        self.videos.setRootIsDecorated(False)
        self.videos.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.videos.currentItemChanged.connect(self._play)
        self.videos.itemSelectionChanged.connect(self._offer_what_can_be_done)

        screen = QVideoWidget()
        self._sound = QAudioOutput()
        self._sound.setMuted(True)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self._sound)
        self.player.setVideoOutput(screen)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)

        self.put_back_button = QPushButton(glyph_icon("undo_arrow", color=_ICON_COLOR), "Put Back")
        self.put_back_button.clicked.connect(self._put_back)
        self.delete_button = QPushButton(glyph_icon("trash", color=_ICON_COLOR), "Delete for Good")
        self.delete_button.clicked.connect(self._delete_for_good)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self, self._delete_for_good)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD)
        layout.addWidget(self.heading)
        layout.addWidget(hint)
        layout.addWidget(_side_by_side(self.videos, _above(screen, self.put_back_button,
                                                           self.delete_button)), stretch=1)

        self._show(weird_piles.marked_weird(), row=0)

    def _show(self, marked: list[weird_piles.MarkedWeird], row: int) -> None:
        self.heading.setText(_counted(len(marked)))
        self.videos.clear()
        for each in marked:
            item = QTreeWidgetItem([each.video.name, _folder(each.goes_back_to)])
            item.setData(0, Qt.ItemDataRole.UserRole, each)
            item.setToolTip(0, str(each.video))
            item.setToolTip(1, _NOWHERE if each.goes_back_to is None else str(each.goes_back_to))
            self.videos.addTopLevelItem(item)
        self.videos.setCurrentItem(self.videos.topLevelItem(min(row, len(marked) - 1)))
        self._offer_what_can_be_done()

    def _play(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        self.player.setSource(QUrl.fromLocalFile(str(_marked(item).video)))
        self.player.play()

    def _put_back(self) -> None:
        self._settle(weird_piles.put_back)

    def _delete_for_good(self) -> None:
        chosen = self._chosen()
        if not chosen:
            return
        which = chosen[0].video.name if len(chosen) == 1 else f"these {len(chosen)} videos"
        asked = QMessageBox.question(
            self, "Delete for Good", f"Delete {which} for good? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if asked == QMessageBox.StandardButton.Yes:
            self._settle(weird_piles.delete_for_good)

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
        self.put_back_button.setEnabled(
            bool(chosen) and all(marked.goes_back_to is not None for marked in chosen))
        self.delete_button.setEnabled(bool(chosen))

    def _let_go(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())


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


def _folder(goes_back_to: Path | None) -> str:
    if goes_back_to is None:
        return "can't tell"
    return str(goes_back_to.parent.relative_to(config.VIDEO_SEARCH_ROOT))
