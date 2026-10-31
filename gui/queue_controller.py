"""The Upscale Queue window's keeper: one window at a time, its verbs answered
through the pipeline module off the window's thread.

The window asks and shows (gui/queue_window.py); the pipeline module is the
window layer's one door to the non-AI stage (evolver.py). Two things this
cannot do itself, it says for the app to answer: a run is wanted now, and the
encode should be parked for whoever is at the computer.
"""

from __future__ import annotations

from functools import partial

from PyQt6.QtCore import QObject, pyqtSignal

import evolver
from gui.background import BackgroundQueue
from gui.one_window import OneWindow
from gui.queue_window import UpscaleQueueWindow


class QueueController(QObject):
    #: The trigger of the run wanted now: the encode asked for starts on a run
    #: and nowhere else, so asking brings the next run forward.
    run_wanted = pyqtSignal(str)
    #: Park the encode for whoever is at the computer now, rather than at the
    #: presence poll's next tick.
    presence_poll_wanted = pyqtSignal()

    def __init__(self, parent_window, background: BackgroundQueue, parent=None):
        super().__init__(parent)
        self._parent_window = parent_window
        self._background = background
        self._window = OneWindow()

    @property
    def is_on_screen(self) -> bool:
        return self._window.is_on_screen

    def show(self) -> None:
        if self._window.show(self._wired_window) is not None:
            self.refresh()

    def refresh(self) -> None:
        if self._window.current is not None:
            self._background.run(evolver.upscale_lineup, then=self._draw)

    def _wired_window(self) -> UpscaleQueueWindow:
        window = UpscaleQueueWindow(self._parent_window)
        window.arranged.connect(self._arrange)
        window.placed_first.connect(self._put_first)
        window.now_requested.connect(self._ask_for_now)
        window.now_withdrawn.connect(self._withdraw)
        window.refresh_wanted.connect(self.refresh)
        return window

    def _draw(self, lineup) -> None:
        if self._window.current is not None:
            self._window.current.show_lineup(lineup)

    def _arrange(self, videos: list) -> None:
        self._background.run(partial(evolver.arrange_upscale_queue, videos))

    def _put_first(self, video: str) -> None:
        self._background.run(partial(evolver.upscale_next, video), then=lambda _: self.refresh())

    def _ask_for_now(self, video: str) -> None:
        self._background.run(partial(evolver.upscale_now, video), then=self._start_what_was_asked_for)

    def _start_what_was_asked_for(self, _) -> None:
        self.refresh()
        self.run_wanted.emit("manual")

    def _withdraw(self) -> None:
        self._background.run(evolver.withdraw_upscale_now, then=self._park_if_present)

    def _park_if_present(self, _) -> None:
        self.presence_poll_wanted.emit()
        self.refresh()
