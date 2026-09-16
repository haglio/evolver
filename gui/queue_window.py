"""The upscale queue: what is being upscaled now, and the line waiting its turn.

Two things this window is for. Seeing the order — the stage picks it by watch
score and a few other signals, and until now the only way to read it was a
count in a log line. And changing it: a video dragged up the list is pinned
where it was dropped, and one dropped on the "upscaling now" box is started
right away, which is what a video downloaded five minutes ago needs.

The window asks and shows; the app answers. Every verb it offers is a signal
the app wires to ``evolver``, because the pipeline is the one thing that
touches the library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import qtawesome as qta
from PyQt6.QtCore import QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from shared_ui.colors import BLUE, BORDER_PANEL, TEXT_SECONDARY
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD

from util import upscale_lineup

if TYPE_CHECKING:
    from util.upscale_lineup import Lineup, Now

# What a dragged row carries besides Qt's own payload: the video's path within
# the library, so the box it lands on knows what was dropped without reaching
# back into the list's selection.
VIDEO_MIME = "application/x-evolver-video"

_ICON_COLOR = TEXT_SECONDARY.name()

# How often an open window asks for the lineup again. The encode it is watching
# is parked and thawed by a poll of its own between the ten-minute runs, and its
# percent climbs the whole time.
REFRESH_SECONDS = 15.0

# What each state of the video in flight reads as, in the window's own words.
_STATE_WORDS = {
    upscale_lineup.UPSCALING: "Upscaling",
    upscale_lineup.PAUSED: "Paused while you're at the computer",
    upscale_lineup.ASKED_FOR: "Upscaling at your request",
    upscale_lineup.STARTING: "Starting at your request",
    upscale_lineup.FINISHING: "Finished encoding; Evolver files it on its next run",
}

# Why a video asked for has not started yet. The stage's own words for these
# are in its log and its run record; these are the same holds, said to the
# person waiting.
_HELD_BACK_WORDS = {
    "topaz_busy": "waiting for another Topaz upscale to finish",
    "low_ram": "waiting for memory to free up",
    "ai_clips_waiting": "waiting for the newly downloaded AI clips, which go first",
    "low_disk": "waiting for room on the drive",
    "topaz_sign_in_expired": "waiting for you to sign in to the Topaz Video app",
}


def running_time(seconds: float | None) -> str:
    """``1:03:24`` for an hour-long scene, ``4:12`` for a short one."""
    if seconds is None:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def dropped_video(mime: QMimeData) -> str:
    """The video a drag is carrying, or ``""`` when it is carrying none."""
    return bytes(mime.data(VIDEO_MIME)).decode("utf-8") if mime.hasFormat(VIDEO_MIME) else ""


class _NowBox(QFrame):
    """The video in flight, and the one place a drop means "start this now"."""

    dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowBox")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAcceptDrops(True)
        self._plain_border()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        layout.setSpacing(GAP_SMALL)

        top = QHBoxLayout()
        self.name_label = QLabel()
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setWordWrap(True)
        top.addWidget(self.name_label, stretch=1)
        self.length_label = QLabel()
        self.length_label.setStyleSheet(f"color: {TEXT_SECONDARY.name()}")
        top.addWidget(self.length_label)
        layout.addLayout(top)

        self.state_label = QLabel()
        self.state_label.setStyleSheet(f"color: {TEXT_SECONDARY.name()}")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)

    def show_now(self, now: Now | None) -> None:
        if now is None:
            self.name_label.setText("Nothing is being upscaled")
            self.length_label.setText("")
            self.state_label.setText("Drop a video here to upscale it right away")
            self.bar.setVisible(False)
            return
        self.name_label.setText(now.entry.name)
        self.length_label.setText(running_time(now.entry.seconds))
        self.state_label.setText(_state_words(now))
        self.bar.setVisible(now.percent is not None)
        self.bar.setValue(now.percent or 0)

    def dragEnterEvent(self, event):
        if dropped_video(event.mimeData()):
            self._lit_border()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._plain_border()
        event.accept()

    def dropEvent(self, event):
        self._plain_border()
        video = dropped_video(event.mimeData())
        if not video:
            event.ignore()
            return
        # Copy rather than move: a move would have the list remove the row it
        # was dragged from, and the window is about to be rebuilt anyway.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.dropped.emit(video)

    def _plain_border(self):
        self._border(BORDER_PANEL.name())

    def _lit_border(self):
        self._border(BLUE.name())

    def _border(self, color: str):
        self.setStyleSheet(f"QFrame#nowBox {{ border: 1px solid {color}; border-radius: 4px; }}")


class _QueueTree(QTreeWidget):
    """The line of videos waiting, in the order the stage will take them."""

    moved = pyqtSignal(str)
    drag_ended = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["", "Video", "Length"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(1, self.header().ResizeMode.Stretch)
        self.header().setSectionResizeMode(0, self.header().ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, self.header().ResizeMode.ResizeToContents)
        self._dragging = False

    @property
    def is_dragging(self) -> bool:
        """Whether a drag is in flight, which a rebuild would pull apart.

        ``QDrag.exec`` runs an event loop of its own, so the refresh timer goes
        on firing while a row is held in the air.
        """
        return self._dragging

    def videos(self) -> list[str]:
        return [self.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)
                for row in range(self.topLevelItemCount())]

    def move_video(self, video: str, row: int) -> None:
        """Put *video* at *row*, counting the rows as they are now."""
        was = self.videos().index(video)
        item = self.takeTopLevelItem(was)
        self.insertTopLevelItem(row - 1 if row > was else row, item)
        self.setCurrentItem(item)
        self.moved.emit(video)

    def mimeData(self, items):
        carried = super().mimeData(items)
        video = items[0].data(0, Qt.ItemDataRole.UserRole) if items else ""
        carried.setData(VIDEO_MIME, str(video).encode("utf-8"))
        return carried

    def startDrag(self, actions):
        self._dragging = True
        try:
            super().startDrag(actions)
        finally:
            self._dragging = False
            self.drag_ended.emit()

    def dropEvent(self, event):
        video = dropped_video(event.mimeData())
        if not video or video not in self.videos():
            event.ignore()
            return
        self.move_video(video, self._dropped_row(event))
        # The move is done, so Qt must not also remove the row it came from,
        # which is what it does for a drop it is told was a move.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _dropped_row(self, event) -> int:
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            return self.topLevelItemCount()
        below = QAbstractItemView.DropIndicatorPosition.BelowItem
        return index.row() + (1 if self.dropIndicatorPosition() == below else 0)


class UpscaleQueueWindow(QDialog):
    """The queue window: it shows a lineup, and says what the user did to it."""

    #: The videos now pinned, in the order they are to be taken.
    arranged = pyqtSignal(list)
    #: The video to start right away.
    now_requested = pyqtSignal(str)
    #: Asking for the lineup again, while the window is open to show it.
    refresh_wanted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver — Upscale Queue")
        self.setMinimumSize(560, 400)
        self.resize(820, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        layout.setSpacing(MARGIN_STANDARD)

        layout.addWidget(_heading("Upscaling now"))
        self._now_box = _NowBox()
        self._now_box.dropped.connect(self.now_requested)
        layout.addWidget(self._now_box)

        self._up_next_heading = _heading("Up next")
        layout.addWidget(self._up_next_heading)

        hint = QLabel("Drag to reorder. Drop a video on the box above to "
                      "upscale it right away, whatever else is running.")
        hint.setStyleSheet(f"color: {TEXT_SECONDARY.name()}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tree = _QueueTree()
        self._tree.moved.connect(self._on_moved)
        self._tree.drag_ended.connect(self._draw_what_waited)
        layout.addWidget(self._tree, stretch=1)

        self._pinned: set[str] = set()
        self._held: Lineup | None = None

        self._clock = QTimer(self)
        self._clock.setInterval(int(REFRESH_SECONDS * 1000))
        self._clock.timeout.connect(self.refresh_wanted)

    def show_lineup(self, lineup: Lineup) -> None:
        """Draw *lineup*, or hold it until the row in the air has landed."""
        if self._tree.is_dragging:
            self._held = lineup
            return
        self._held = None
        self._now_box.show_now(lineup.now)
        self._up_next_heading.setText(_up_next_heading(lineup.up_next))
        self._pinned = {entry.video for entry in lineup.up_next if entry.pinned}
        scrolled = self._tree.verticalScrollBar().value()
        self._tree.clear()
        for entry in lineup.up_next:
            item = QTreeWidgetItem(["", entry.name, running_time(entry.seconds)])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.video)
            item.setToolTip(1, entry.video)
            item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsDragEnabled)
            self._tree.addTopLevelItem(item)
        self._mark_places()
        self._tree.verticalScrollBar().setValue(scrolled)

    def showEvent(self, event):
        super().showEvent(event)
        self._clock.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._clock.stop()

    def _draw_what_waited(self) -> None:
        """Draw whatever lineup arrived while the row was in the air."""
        if self._held is not None:
            self.show_lineup(self._held)

    def _on_moved(self, video: str) -> None:
        videos = self._tree.videos()
        placed = max([videos.index(video)]
                     + [row for row, name in enumerate(videos) if name in self._pinned])
        order = videos[:placed + 1]
        self._pinned = set(order)
        self._mark_places()
        self.arranged.emit(order)

    def _mark_places(self) -> None:
        """Number every row, and mark the ones the user placed by hand."""
        for row in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(row)
            item.setText(0, str(row + 1))
            placed = item.data(0, Qt.ItemDataRole.UserRole) in self._pinned
            item.setIcon(0, qta.icon("fa5s.thumbtack", color=_ICON_COLOR) if placed
                         else qta.icon("fa5s.thumbtack", color="transparent"))
            item.setToolTip(0, "You put this one here" if placed
                            else "Evolver's own order: most watched first")


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _up_next_heading(entries: tuple) -> str:
    hours = sum(entry.seconds or 0.0 for entry in entries) / 3600
    videos = f"{len(entries)} video" + ("" if len(entries) == 1 else "s")
    return f"Up next — {videos}, {hours:.1f} hours of footage"


def _state_words(now: Now) -> str:
    words = _STATE_WORDS.get(now.state, now.state)
    if now.held_back:
        return f"{words} — {_HELD_BACK_WORDS.get(now.held_back, now.held_back)}"
    if now.percent is not None:
        return f"{words} — {now.percent}% done"
    return words
