
from __future__ import annotations

import logging

from app_support.win32 import TaskbarApp, dress_window, set_app_user_model_id
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget
from shared_ui.preview_icon import app_icon, icon_file

import config
from gui import branch_session
from util.preview import shown_as

log = logging.getLogger(__name__)

# The Windows AppUserModelID: a pinned shortcut belongs to this string.
APP_MODEL_ID = "Evolver.TrayApp"
LETTER = config.PROJECT_DIR / "icon.ico"


def identity() -> str:
    return branch_session.model_id(APP_MODEL_ID)


def taskbar_app() -> TaskbarApp:
    return TaskbarApp(name=branch_session.app_name(), icon=icon_file(LETTER, shown_as(), config.LOCAL_STATE_DIR),
                      relaunch=branch_session.relaunch_command())


# Run by pythonw.exe, a Qt app is Python to the Windows shell: its taskbar buttons carry
# Python's icon, and a pin made from one starts bare Python.
def claim(app: QApplication) -> QObject:
    claimed = identity()
    try:
        set_app_user_model_id(claimed)
    except OSError:
        log.warning("Could not claim the taskbar identity", exc_info=True)
    app.setWindowIcon(app_icon(LETTER, shown_as()))
    dresser = _WindowDresser(app, claimed, taskbar_app())
    app.installEventFilter(dresser)
    return dresser


class _WindowDresser(QObject):

    def __init__(self, app: QApplication, identity: str, taskbar_app: TaskbarApp):
        super().__init__(app)
        self._identity = identity
        self._taskbar_app = taskbar_app

    # Qt sends Show before it maps the window, so before Windows makes the taskbar button out of
    # what the window wears.
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            try:
                dress_window(int(watched.winId()), self._identity, self._taskbar_app)
            except OSError:
                log.warning("Could not tell the taskbar what %r is", watched.windowTitle(),
                            exc_info=True)
        return False
