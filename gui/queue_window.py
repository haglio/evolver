"""The upscale queue: one list, with whatever is being upscaled on the first row.

Two things this window is for. Seeing the order — the stage picks it by watch
score and a few other signals, and until now the only way to read it was a
count in a log line. And changing it: a video dragged up the list is kept where
it was dropped, and one dragged to the top is the next one upscaled, ahead of
whatever the machine was on.

The first row is the one the machine is on, and the arrow beside it says
whether it goes ahead while somebody is at the computer: filled it runs anyway,
hollow it waits until nobody is. Clicking it switches between the two.

The window asks and shows; the app answers. Every verb it offers is a signal
the app wires to ``evolver``, because the pipeline is the one thing that
touches the library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import qtawesome as qta
from PyQt6.QtCore import QMimeData, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from shared_ui.colors import BLUE, TEXT_MUTED
from shared_ui.spacing import MARGIN_STANDARD

from util import upscale_lineup

if TYPE_CHECKING:
    from util.upscale_lineup import Head, Lineup

# What a dragged row carries besides Qt's own payload: the video's path within
# the library, so a drop knows what was dropped without reaching back into the
# list's selection.
VIDEO_MIME = "application/x-evolver-video"

# The family's muted gray rather than its secondary text, which is a near-white
# for the dark chrome this app draws none of: these sit on a window Windows
# colors, and the same gray is what the run history marks its inert rows with.
_MUTED = TEXT_MUTED.name()

# How often an open window asks for the lineup again. The encode it is watching
# is parked and thawed by a poll of its own between the ten-minute runs, and its
# percent climbs the whole time.
REFRESH_SECONDS = 15.0

# What each state of the first row reads as, in the window's own words.
_STATE_WORDS = {
    upscale_lineup.NEXT: "Next, once you're away from the computer",
    upscale_lineup.UPSCALING: "Upscaling",
    upscale_lineup.PAUSED: "Paused while you're at the computer",
    upscale_lineup.ASKED_FOR: "Upscaling at your request",
    upscale_lineup.STARTING: "Starting at your request",
    upscale_lineup.FINISHING: "Done upscaling; Evolver's next run replaces the original with it",
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

_RUNS_NOW_TIP = ("Upscaling now, even while you're at the computer. "
                 "Click to let it wait until you are away.")
_WAITS_TIP = "Click to upscale this one now, even while you're at the computer."


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


class _QueueTree(QTreeWidget):
    """The queue, in the order the stage will take it, rearranged by dragging."""

    #: A video and the row it was dropped on, counting from zero.
    moved = pyqtSignal(str, int)
    drag_ended = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHeaderLabels(["", "Video", "", "Length"])
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
        for column in (0, 2, 3):
            self.header().setSectionResizeMode(column, self.header().ResizeMode.ResizeToContents)
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
        """Put *video* on *row*, counting the rows as they are now."""
        was = self.videos().index(video)
        if row in (was, was + 1):
            return  # dropped back where it already was
        item = self.takeTopLevelItem(was)
        self.insertTopLevelItem(row - 1 if row > was else row, item)
        self.setCurrentItem(item)
        self.moved.emit(video, self.videos().index(video))

    def mimeData(self, items):
        carried = super().mimeData(items)
        video = items[0].data(0, Qt.ItemDataRole.UserRole) if items else ""
        carried.setData(VIDEO_MIME, str(video).encode("utf-8"))
        return carried

    def startDrag(self, actions):
        """Carry the row, and leave the list alone -- the drop moves it.

        Not ``super()``: what QAbstractItemView does after a move is to remove
        the rows the drag started from, and here the drop has already put that
        row where it belongs, so the removal takes the row the user just placed
        back off the list. It reappeared a refresh later, at the place it had
        been dropped, which is what the user saw as a row vanishing for a
        minute.
        """
        item = self.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return
        rect = self.visualItemRect(item)
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        drag.setPixmap(self.viewport().grab(rect))
        drag.setHotSpot(QPoint(rect.width() // 10, rect.height() // 2))
        self._dragging = True
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._dragging = False
            self.drag_ended.emit()

    def dropEvent(self, event):
        video = dropped_video(event.mimeData())
        if not video or video not in self.videos():
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.move_video(video, self.dropped_row(event.position().toPoint()))

    def dropped_row(self, pos: QPoint) -> int:
        """Which row a drop at *pos* means, by the half of a row it landed in."""
        index = self.indexAt(pos)
        if not index.isValid():
            return self.topLevelItemCount()
        return index.row() + (0 if pos.y() < self.visualRect(index).center().y() else 1)


class UpscaleQueueWindow(QDialog):
    """The queue window: it shows a lineup, and says what the user did to it."""

    #: The videos now placed by hand, in the order they are to be taken.
    arranged = pyqtSignal(list)
    #: The video dragged to the top: next, at the usual moment.
    placed_first = pyqtSignal(str)
    #: The video to upscale now, whoever is at the computer.
    now_requested = pyqtSignal(str)
    #: The video on the first row goes back to waiting until you are away.
    now_withdrawn = pyqtSignal()
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

        self._heading = QLabel()
        font = self._heading.font()
        font.setBold(True)
        self._heading.setFont(font)
        layout.addWidget(self._heading)

        hint = QLabel("Drag to reorder; the top video is the next one upscaled. Its "
                      "arrow upscales it right away, even while you're at the computer.")
        hint.setStyleSheet(f"color: {_MUTED}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tree = _QueueTree()
        self._tree.moved.connect(self._on_moved)
        self._tree.drag_ended.connect(self._draw_what_waited)
        self._tree.itemClicked.connect(self._on_clicked)
        layout.addWidget(self._tree, stretch=1)

        self._pinned: set[str] = set()
        self._head: Head | None = None
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
        self._head = lineup.head
        self._heading.setText(_queue_heading(lineup.rows))
        self._pinned = {entry.video for entry in lineup.rows if entry.pinned}
        scrolled = self._tree.verticalScrollBar().value()
        self._tree.clear()
        for entry in lineup.rows:
            item = QTreeWidgetItem(["", entry.name, "", running_time(entry.seconds)])
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setData(0, Qt.ItemDataRole.UserRole, entry.video)
            item.setToolTip(1, entry.video)
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

    def _on_clicked(self, item, column: int) -> None:
        """The arrow, which only the first row has and only column zero is."""
        if column != 0 or item is not self._tree.topLevelItem(0) or self._head is None:
            return
        if self._head.state == upscale_lineup.FINISHING:
            return
        if self._head.runs_now:
            self._head = upscale_lineup.Head(
                upscale_lineup.UPSCALING if self._head.state == upscale_lineup.ASKED_FOR
                else upscale_lineup.NEXT, self._head.percent)
            self._mark_places()
            self.now_withdrawn.emit()
            return
        self._head = upscale_lineup.Head(upscale_lineup.STARTING)
        self._mark_places()
        self.now_requested.emit(self._tree.videos()[0])

    def _on_moved(self, video: str, row: int) -> None:
        if row == 0:
            self._head = upscale_lineup.Head(upscale_lineup.NEXT)
            self._mark_places()
            self.placed_first.emit(video)
            return
        videos = self._tree.videos()
        placed = max([row] + [at for at, name in enumerate(videos) if name in self._pinned])
        order = videos[:placed + 1]
        self._pinned = set(order)
        self._mark_places()
        self.arranged.emit(order)

    def _mark_places(self) -> None:
        """Number every row, and put the arrow and the state on the first."""
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        for row in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(row)
            head = self._head if row == 0 else None
            item.setText(0, str(row + 1))
            item.setText(2, _state_words(head) if head else "")
            item.setIcon(0, _arrow(head))
            item.setToolTip(0, _arrow_tip(head))
            in_flight = head is not None and head.in_flight
            item.setFlags(flags if in_flight else flags | Qt.ItemFlag.ItemIsDragEnabled)


def _arrow(head: Head | None):
    """The first row's arrow: filled it runs now, hollow it waits."""
    if head is None or head.state == upscale_lineup.FINISHING:
        return qta.icon("fa5s.arrow-alt-circle-right", color="transparent")
    if head.runs_now:
        return qta.icon("fa5s.arrow-alt-circle-right", color=BLUE.name())
    return qta.icon("fa5.arrow-alt-circle-right", color=_MUTED)


def _arrow_tip(head: Head | None) -> str:
    if head is None or head.state == upscale_lineup.FINISHING:
        return ""
    return _RUNS_NOW_TIP if head.runs_now else _WAITS_TIP


def _queue_heading(rows: tuple) -> str:
    if not rows:
        return "Nothing is waiting to be upscaled"
    hours = sum(entry.seconds or 0.0 for entry in rows) / 3600
    videos = f"{len(rows)} video" + ("" if len(rows) == 1 else "s")
    return f"{videos}, {hours:.1f} hours of footage"


def _state_words(head: Head) -> str:
    words = _STATE_WORDS.get(head.state, head.state)
    if head.held_back:
        return f"{words} — {_HELD_BACK_WORDS.get(head.held_back, head.held_back)}"
    if head.percent is not None:
        return f"{words} — {head.percent}% done"
    return words
