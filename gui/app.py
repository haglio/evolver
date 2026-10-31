"""Top-level application wiring: tray, window, scheduler, worker."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from functools import partial

from app_support import production_update
from app_support.loading_screen import AppWindow, meeting_place
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from shared_ui.loading_window import Loading, LoadingCanceled

import config
from gui import branch_session, peer_watch, process_identity, single_instance
from gui.background import BackgroundQueue
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow
from gui.one_window import OneWindow
from gui.palette import apply_accent
from gui.presence_throttle import PresenceThrottle
from gui.queue_controller import QueueController
from gui.run_controller import RunController
from gui.run_history import RunHistory
from gui.run_record import RunRecord, format_run_label
from gui.scheduler import PipelineScheduler
from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog
from gui.sign_in_notice import SignInNotice
from gui.single_instance import InstanceGateway, Outcome
from gui.stats_window import StatsWindow
from gui.tray import EvolverTray
from util import crash_log, run_log
from util.alert import show_error

log = logging.getLogger(__name__)

_UPDATE_CHECK_MS = 60_000

_SHOW_WINDOW = "--show-window"
# AllowSetForegroundWindow's ASFW_ANY: the copy that will want the foreground is
# the launcher's grandchild, whose pid nothing here can know.
_ANY_PROCESS = -1
STEPS = (("Loading Evolver...", 1.0),)


def open_the_loading_screen():
    from shared_ui.loading_process import LoadingProcess  # noqa: PLC0415

    return LoadingProcess.open(
        caption="Evolver Loading", wordmark="Evolver", icon=process_identity.LETTER, preview=branch_session.shown_as(),
        steps=STEPS, cancel_hint="Press Esc to cancel opening Evolver",
        app_id=process_identity.identity(), taskbar=process_identity.taskbar_app())


def _say_the_running_evolver_did_not_answer(app: QApplication) -> None:
    """A wedged Evolver holds the claim while answering nothing, and exiting into
    silence there looks exactly like a shortcut that does nothing."""
    process_identity.claim(app)
    show_error(
        "Evolver",
        "Evolver is already running but did not respond, so its window "
        "could not be opened.\n\nQuit it from the tray icon, or end the "
        "pythonw.exe process, then start Evolver again.",
    )


def _unmarked_note(record, log_path) -> str:
    """Why a run's lines are not on screen, in the window's own words."""
    if record.log_start is None:
        return ("This run predates Evolver marking its runs in the log, so "
                "there is no mark to find its lines by.")
    return (f"{log_path} no longer holds this run's lines: the file has been "
            "replaced or trimmed since the run wrote them.")


def _wire(view, slots: dict) -> None:
    """Connect each of *view*'s commands to the slot of the same name.

    The two sides are held equal on purpose. A control a view offers that
    nothing is wired to is a menu item that does nothing when clicked, and a
    slot no view offers is a command the user cannot reach -- neither shows up
    anywhere else, because a QAction with no connection raises nothing. It
    fails here, while the app is being built and before it has done anything.
    """
    offered = view.commands()
    if set(offered) != set(slots):
        raise ValueError(
            f"{type(view).__name__} offers commands {sorted(offered)}, "
            f"wired to {sorted(slots)}"
        )
    for key, signal in offered.items():
        signal.connect(slots[key])


class EvolverApp:
    """Wires together all GUI components and runs the Qt event loop.

    Split in two on purpose. ``__init__`` only *builds*: it constructs the
    parts and connects them, and touches nothing outside the process. ``start``
    is everything the app *does* -- claim the Windows identity, read the run
    history off disk, start the two timers, show the tray. So constructing one
    names nothing to the shell and starts no timer, which is what lets a test
    build one part without a twenty-second presence poll running for the rest
    of the session.
    """

    def __init__(self, app: QApplication):
        self._app = app
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")
        apply_accent(self._app)

        self._checkout = config.PROJECT_DIR
        self._settings = EvolverSettings.load()
        self._stats = OneWindow()
        # The queue window's reads and verbs reach into the non-AI stage, which
        # a run can hold for as long as starting an encode takes.
        self._background = BackgroundQueue()
        self._log_window: RunLogWindow | None = None
        self._instance = InstanceGateway()
        self._session = branch_session.BranchSession(
            self._instance, a_run_is_going=lambda: self._runs.is_running)
        self._session.leaving.connect(self._shutdown)
        self._sign_in_notice = SignInNotice()

        # Parks and thaws the in-flight non-AI encode between the slow pipeline
        # ticks, so returning to the machine suspends it in seconds. Reads the
        # opt-in at every poll, since it can be switched while it runs.
        self._presence = PresenceThrottle(
            lambda: self._settings.nonai_upscale_enabled)

        # The other half of the pair that keeps both apps up. Evolver starts the
        # broker's tray when it finds it gone, and that tray does the same for
        # Evolver -- which is where Evolver's own supervision comes from, since
        # the tray is revived by a scheduled task and Evolver is revived by the
        # tray. See gui/peer_watch.py.
        self._peer = peer_watch.watch_the_broker()
        self._peer_timer = QTimer()
        self._peer_timer.setInterval(peer_watch.PEER_CHECK_INTERVAL_MS)
        self._peer_timer.timeout.connect(self._peer.tick)

        self._scheduler = PipelineScheduler(interval_minutes=self._settings.interval_minutes)
        self._scheduler.status_changed.connect(self._update_status_display)

        self._window = EvolverMainWindow()
        self._window.setWindowTitle(self._session.name)
        self._window.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        # Not one of the window's commands: those are the toolbar's, named the
        # same on the tray. This one carries the run that was clicked.
        self._window.log_requested.connect(self._show_run_log)

        # The non-AI opt-in is read at every start rather than held from
        # construction: it can be switched between runs.
        self._runs = RunController(
            self._window, lambda: self._settings.nonai_upscale_enabled)
        self._scheduler.run_requested.connect(self._runs.start)
        self._runs.run_started.connect(self._on_run_started)
        self._runs.run_ended.connect(self._on_run_ended)
        self._runs.run_finished.connect(self._on_finished)
        self._runs.run_failed.connect(self._on_error)
        self._runs.run_overran.connect(self._on_overrun)

        self._queue = QueueController(self._window, self._background)
        self._queue.run_wanted.connect(self._runs.start_when_free)
        self._queue.presence_poll_wanted.connect(self._presence.poll)

        shared_commands = {
            "run_now": self._scheduler.run_now,
            "pause": self._toggle_pause,
            "nonai": self._set_nonai_enabled,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "queue": self._queue.show,
            "backfill": self._launch_backfill,
            "review_weird": self._launch_review_weird,
            "restart": self._restart,
        }

        self._tray = EvolverTray(self._session.name, shown_as=branch_session.shown_as())
        self._tray.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        _wire(self._tray, {**shared_commands,
                           "open": self._show_window, "quit": self._session.quit})
        # Quit is the one command that means something different here: from the
        # window it asks first, because the window is where a stray click lands.
        _wire(self._window, {**shared_commands, "quit": self._confirm_quit})

        self._app.commitDataRequest.connect(self._on_session_end)

        self._updates = production_update.UpdateWatch(
            self._checkout, a_good_moment=self._a_good_moment_for_an_update,
            start_again=self._restart, logger=log)
        self._update_timer = QTimer()
        self._update_timer.setInterval(_UPDATE_CHECK_MS)
        self._update_timer.timeout.connect(lambda: self._updates.tick())

    def _a_good_moment_for_an_update(self) -> bool:
        on_screen = (self._window.isVisible(), self._stats.is_on_screen, self._queue.is_on_screen,
                     self._log_window is not None and self._log_window.isVisible())
        return not self._session.is_preview and not self._runs.is_running and not any(on_screen)

    def start(self) -> None:
        """Everything the app does to the machine, in the order it must happen.

        The identity goes first: the taskbar reads it when a window of this
        process first appears, so claiming it after the tray is up is claiming
        it too late.
        """
        process_identity.claim(self._app)
        self._window.refresh_history()
        self._tray.show()
        self._keep_the_schedule()
        self._session.take_the_work()
        self._window.setWindowTitle(self._session.title(datetime.now()))
        if _SHOW_WINDOW in sys.argv:
            self._show_window()

    def _keep_the_schedule(self) -> None:
        """Start the timers only the one running Evolver keeps: the schedule,
        the presence poll that parks the non-AI encode, and the broker watch."""
        # Whatever the user wanted the last time they closed Evolver, starting it
        # is them wanting it up now -- so the stand-down goes before the first
        # peer check, not after it.
        peer_watch.clear_evolver_stand_down()
        self._presence.start()
        self._scheduler.start()
        self._peer_timer.start()
        self._update_timer.start()
        self._peer.tick()

    def run(self) -> int:
        outcome = self._instance.become_evolver(
            as_preview=self._session.is_preview,
            only_if_not_running=single_instance.IF_NOT_RUNNING in sys.argv)
        if outcome is Outcome.UNANSWERED:
            _say_the_running_evolver_did_not_answer(self._app)
        if outcome is not Outcome.CLAIMED:
            return 0
        if (next_launch := meeting_place(os.environ)) is not None:
            next_launch.say_where_the_app_comes_up(AppWindow(size=(self._window.width(), self._window.height())))
        loading = Loading.at_the_click(self._app, log, open_the_loading_screen)
        try:
            for step, _weight in STEPS:
                loading.say(step)
        except LoadingCanceled:
            return 0

        self._instance.serve_launches(steps_aside_for=self._session.steps_aside_for,
                                      on_show=self._show_window,
                                      on_step_aside=self._session.step_aside)
        self.start()
        loading.done()
        return self._app.exec()

    def _show_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _toggle_pause(self):
        if self._scheduler.is_paused:
            self._scheduler.resume()
        else:
            self._scheduler.pause()

    def _set_nonai_enabled(self, enabled: bool):
        """Persist the one-time opt-in; presence polling and the next tick act on it."""
        self._settings.nonai_upscale_enabled = enabled
        self._settings.save()
        self._tray.set_nonai_enabled(enabled)
        self._window.set_nonai_enabled(enabled)

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

    def _show_stats(self):
        window = self._stats.show(partial(StatsWindow, self._window))
        if window is not None:
            self._background.run(partial(RunHistory.read, config.RUNS_DIR),
                                 then=partial(self._chart_history, window))

    def _chart_history(self, window: StatsWindow, history: RunHistory):
        if window is self._stats.current:
            window.show_history(history)

    def _show_run_log(self, record: RunRecord):
        """Open the log where this run wrote, rather than at its top.

        Rebuilt each time rather than raised like the stats window: a different
        run is different content, and the one before it is closed and dropped
        so a window per click cannot pile up under the main one.
        """
        if self._log_window is not None:
            self._log_window.close()
            self._log_window.deleteLater()
        # Read once and handed on: the reader takes the path, so it does not
        # have to reach for the ambient config itself.
        log_path = config.LOG_FILE
        text = run_log.read_run(
            log_path, record.id, record.log_start, record.log_end)
        note = "" if text is not None else _unmarked_note(record, log_path)
        self._log_window = RunLogWindow(
            format_run_label(record.started_at, record.duration_seconds),
            text or "", note, self._window,
        )
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def _launch_backfill(self):
        self._launch_tool("backfill_app.py")

    def _launch_review_weird(self):
        self._launch_tool("review_weird_app.py")

    def _launch_tool(self, script: str):
        # Its own process: a tool plays video, and a media backend that wedges
        # or crashes must not take the tray down with it.
        subprocess.Popen(
            [sys.executable, str(self._checkout / script)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def _update_status_display(self, status):
        """Push scheduling state to tray and window."""
        self._tray.show_schedule(status)
        self._window.show_schedule(status)

    def _on_run_started(self):
        self._scheduler.mark_running()

    def _on_run_ended(self):
        self._scheduler.mark_idle()
        self._window.refresh_history()
        # A run is what starts, promotes and fails encodes, so the queue on
        # screen is a run old the moment one ends.
        self._queue.refresh()

    def _notify(self, body: str, icon: QSystemTrayIcon.MessageIcon, msecs: int):
        """Say something in a tray balloon, if the user asked for balloons."""
        if not self._settings.enable_toasts:
            return
        self._tray.showMessage("Evolver", body, icon, msecs)

    def _on_finished(self, record):
        succeeded = record.status == "success"
        status = "completed" if succeeded else "completed with errors"
        self._notify(
            f"Pipeline {status} in {record.duration_seconds:.0f}s",
            QSystemTrayIcon.MessageIcon.Information if succeeded
            else QSystemTrayIcon.MessageIcon.Warning,
            5000,
        )
        self._sign_in_notice.after_run(record, time.monotonic())

    def _on_error(self, message: str):
        self._notify(f"Pipeline error: {message}",
                     QSystemTrayIcon.MessageIcon.Critical, 8000)

    def _on_overrun(self):
        """An overrun is news and nothing else: the run really is still going.

        No mark_idle and no set_running(False) -- either would re-enable Run
        Now and let the scheduler tick into a run that cannot start.
        """
        self._notify(
            f"Pipeline still running past the {config.PIPELINE_WALL_TIMEOUT_SECONDS // 60}-minute "
            "limit; stopping after the current stage. New runs wait until it exits.",
            QSystemTrayIcon.MessageIcon.Critical,
            8000,
        )

    def _on_session_end(self, manager):
        """Handle Windows session-management events (shutdown, logoff, installer restart).

        Logs the event, then quits the way the tray menu does: the scheduler
        stops and the worker thread is given five seconds to finish its stage.
        What it deliberately does NOT do is touch the detached processes -- the
        in-flight non-AI encode, the backfill tool -- because those are
        detached precisely so they outlive this one, and Windows is about to
        end the session for all of them anyway.
        """
        crash_log.write_info(
            "Windows session end requested:",
            f"allowsInteraction={manager.allowsInteraction()}\n",
        )
        self._shutdown()

    def _confirm_quit(self):
        result = QMessageBox.question(
            self._window,
            "Quit Evolver",
            self._session.quit_question(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._session.quit()

    def _restart(self):
        showing = self._window.isVisible()
        launcher = self._session.restart_launcher(showing=showing)
        production_update.start_again_after(os.getpid(), self._checkout / launcher)
        if showing:
            ctypes.windll.user32.AllowSetForegroundWindow(_ANY_PROCESS)
        self._shutdown()

    def _shutdown(self):
        self._instance.stop_serving()
        self._background.stop()
        self._runs.wait_for_exit(5000)
        self._scheduler.stop()
        self._peer_timer.stop()
        self._update_timer.stop()
        self._tray.hide()
        self._app.quit()
