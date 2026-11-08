from __future__ import annotations

import os

# Qt's offscreen platform: no window or tray icon appears on the computer the suite runs on.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from gui.app import EvolverApp
from util.upscale_queue import UpscaleQueue

# A QApplication has to exist before the first GUI module is imported.
QAPP = QApplication.instance() or QApplication([])

EMPTY_QUEUE = UpscaleQueue(rows=(), head=None)


class DoneWhileTheTestsPatchesStand:
    def run(self, work, then=None):
        answer = work()
        if then is not None:
            then(answer)

    def stop(self):
        pass


def row_ground_past_its_text(view, row: int) -> str:
    QAPP.processEvents()
    last_cell = view.visualRect(view.model().index(row, view.model().columnCount() - 1))
    painted = view.viewport().grab().toImage()
    return painted.pixelColor(last_cell.right() - 2, last_cell.center().y()).name()


def build_evolver_app(owner):
    app = EvolverApp(QAPP)
    if hasattr(owner, "addCleanup"):
        owner.addCleanup(retire_without_quitting_the_shared_application, app)
    else:
        owner.addfinalizer(lambda: retire_without_quitting_the_shared_application(app))
    return app


def _unhook_session_end_unless_a_test_already_did(app) -> None:
    with contextlib.suppress(TypeError):
        app._app.commitDataRequest.disconnect(app._on_session_end)


def retire_without_quitting_the_shared_application(app) -> None:
    app._presence.stop()
    app._runs._watchdog.stop()
    app._peer_timer.stop()
    app._update_timer.stop()
    app._scheduler.stop()
    _unhook_session_end_unless_a_test_already_did(app)
    app._tray.hide()
    app._tray.setParent(None)
    app._tray.deleteLater()
    app._window.close()
    app._window.deleteLater()
    QAPP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
