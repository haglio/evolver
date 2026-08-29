"""The one QApplication these tests share, and the one way to build an app on it.

Twelve test modules each opened with ``_app = QApplication.instance() or
QApplication([])``, and the four that needed an ``EvolverApp`` repeated the same
``with patch("gui.app.QApplication", return_value=_app)`` twenty-five times with
no teardown anywhere. Every one of those instances starts a twenty-second
presence timer and a watchdog timer, adds another ``commitDataRequest`` receiver
to the one shared QApplication, and mutates that application's window icon, name
and quit-on-last-window-closed flag -- and then lives for the rest of the run.
``test_progress_popup.py`` and ``test_backfill_window.py`` already took their
widgets down again; the heaviest object in the repo did not.
"""
from __future__ import annotations

import os
from unittest.mock import patch

# Before the QApplication below: agents run this suite on every commit, on the
# machine Evolver itself runs on, and a tray icon or a window appearing there is
# the app the user is already using flickering at him. The merge gate sets this
# in its own env, which does nothing for a run started by hand. setdefault lets a
# developer override it to watch something on a real display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402  -- after the platform is set

# Built at import, not in a fixture: the GUI modules construct widgets at class
# scope and a QApplication has to exist before the first of them is imported.
# conftest.py imports this module for that reason, so it happens once, before any
# test module.
QAPP = QApplication.instance() or QApplication([])


def build_evolver_app(owner):
    """An ``EvolverApp`` on the shared QApplication, retired when the test ends.

    ``owner`` is whatever can register the teardown: a ``unittest.TestCase`` or
    a pytest ``request`` fixture. Wrap any other patches the test needs around
    the call; this owns only the QApplication substitution and the teardown.
    """
    from gui.app import EvolverApp

    with patch("gui.app.QApplication", return_value=QAPP):
        app = EvolverApp()
    if hasattr(owner, "addCleanup"):
        owner.addCleanup(retire_evolver_app, app)
    else:
        owner.addfinalizer(lambda: retire_evolver_app(app))
    return app


def retire_evolver_app(app) -> None:
    """Stop what an ``EvolverApp`` started and let go of the shared application.

    Not ``_quit()``: that asks the real application to exit, which would take the
    suite's own QApplication with it. This undoes construction instead -- both
    timers, the session-end connection, the tray and the window.
    """
    app._presence_monitor.stop()
    app._watchdog.stop()
    app._scheduler.stop()
    try:
        app._app.commitDataRequest.disconnect(app._on_session_end)
    except TypeError:
        pass  # a test that replaced the handler already broke the connection
    app._tray.hide()
    app._tray.setParent(None)
    app._tray.deleteLater()
    app._window.close()
    app._window.deleteLater()
