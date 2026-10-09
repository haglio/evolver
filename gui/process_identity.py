"""What an Evolver process tells Windows it is, so each window it shows says Evolver.

A PyQt app launched through ``pythonw.exe`` is, as far as the shell is
concerned, pythonw: its taskbar buttons belong to Python, carry Python's icon,
and a pin made from one relaunches Python with no arguments. The tray and each
tool it starts are such processes, and two things fix it -- naming the process,
and dressing each window it shows -- both of them things the app *does* to the
machine it is running on, which is why they are here and not in a constructor.
"""

from __future__ import annotations

import logging

from app_support.win32 import TaskbarApp, dress_window, set_app_user_model_id
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget
from shared_ui.preview_icon import app_icon, icon_file

import config
from gui import branch_session
from util.preview import shown_as

log = logging.getLogger(__name__)

# The Windows identity contract. A pinned shortcut belongs to whatever this
# says, so it is the one string that must not drift.
APP_MODEL_ID = "Evolver.TrayApp"


def claim(app: QApplication) -> QObject:
    """Name this process to the shell, and dress each window *app* shows from now on
    in Evolver's letter.

    A refusal is logged, not raised: a button wearing Python's icon is still a
    button, and an icon is never worth failing to start over.
    """
    identity = branch_session.model_id(APP_MODEL_ID)
    try:
        set_app_user_model_id(identity)
    except OSError:
        log.warning("Could not claim the taskbar identity", exc_info=True)
    letter, shown = config.PROJECT_DIR / "icon.ico", shown_as()
    app.setWindowIcon(app_icon(letter, shown))
    dresser = _WindowDresser(app, identity, TaskbarApp(
        name=branch_session.app_name(),
        icon=icon_file(letter, shown, config.LOCAL_STATE_DIR),
        relaunch=branch_session.relaunch_command(),
    ))
    app.installEventFilter(dresser)
    return dresser


class _WindowDresser(QObject):
    """Dresses a window at its Show event, which Qt sends before mapping the
    window -- so before Windows makes its taskbar button out of what it wears."""

    def __init__(self, app: QApplication, identity: str, taskbar_app: TaskbarApp):
        super().__init__(app)
        self._identity = identity
        self._taskbar_app = taskbar_app

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            try:
                dress_window(int(watched.winId()), self._identity, self._taskbar_app)
            except OSError:
                log.warning("Could not tell the taskbar what %r is", watched.windowTitle(),
                            exc_info=True)
        return False
