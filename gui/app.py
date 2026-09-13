"""Top-level application wiring: tray, window, scheduler, worker."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

import config
from gui import peer_watch, process_identity
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow
from gui.palette import apply_accent
from gui.presence_throttle import PresenceThrottle
from gui.run_controller import RunController
from gui.run_record import RunRecord, format_run_label, load_runs
from gui.scheduler import PipelineScheduler
from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog
from gui.sign_in_notice import SignInNotice
from gui.single_instance import InstanceGateway
from gui.stats_window import StatsWindow
from gui.tray import EvolverTray
from util import crash_log, run_log
from util.alert import show_error

log = logging.getLogger(__name__)


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
    history off disk, start the two timers, show the tray. Merely constructing
    one used to name this process to the shell and begin a twenty-second
    presence poll, which is why every test of any one part had to build the
    whole thing and then live with a running timer for the rest of the session.
    """

    def __init__(self):
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")
        apply_accent(self._app)

        self._settings = EvolverSettings.load()
        self._stats_window: StatsWindow | None = None
        self._log_window: RunLogWindow | None = None
        self._instance = InstanceGateway()
        self._sign_in_notice = SignInNotice()

        # Parks and thaws the in-flight non-AI encode between the slow pipeline
        # ticks, so returning to the machine suspends it in seconds. Reads the
        # opt-in at every poll, since the tray toggle flips it while it runs.
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

        self._tray = EvolverTray()
        self._app.setWindowIcon(self._tray.icon())
        self._tray.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        _wire(self._tray, {
            "open": self._show_window,
            "run_now": self._scheduler.run_now,
            "pause": self._toggle_pause,
            "nonai": self._set_nonai_enabled,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "backfill": self._launch_backfill,
            "restart": self._restart,
            "quit": self._quit_by_request,
        })

        self._app.commitDataRequest.connect(self._on_session_end)

        self._window = EvolverMainWindow()
        # Quit is the one command that means something different here: from the
        # window it asks first, because the window is where a stray click lands.
        _wire(self._window, {
            "run_now": self._scheduler.run_now,
            "pause": self._toggle_pause,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "restart": self._restart,
            "quit": self._confirm_quit,
        })
        # Not one of the window's commands: those are the toolbar's, named the
        # same on the tray. This one carries the run that was clicked.
        self._window.log_requested.connect(self._show_run_log)

        # The non-AI toggle is read at every start rather than held from
        # construction: the tray flips it between runs.
        self._runs = RunController(
            self._window, lambda: self._settings.nonai_upscale_enabled)
        self._scheduler.run_requested.connect(self._runs.start)
        self._runs.run_started.connect(self._on_run_started)
        self._runs.run_ended.connect(self._on_run_ended)
        self._runs.run_finished.connect(self._on_finished)
        self._runs.run_failed.connect(self._on_error)
        self._runs.run_overran.connect(self._on_overrun)

    def start(self) -> None:
        """Everything the app does to the machine, in the order it must happen.

        The identity goes first: the taskbar reads it when a window of this
        process first appears, so claiming it after the tray is up is claiming
        it too late.
        """
        process_identity.claim(int(self._window.winId()))
        # Whatever the user wanted the last time they closed Evolver, starting it
        # is them wanting it up now -- so the stand-down goes before the first
        # peer check, not after it.
        peer_watch.clear_evolver_stand_down()
        self._window.refresh_history()
        self._presence.start()
        self._tray.show()
        self._scheduler.start()
        self._peer_timer.start()
        self._peer.tick()
        if "--show-window" in sys.argv:
            self._show_window()

    def run(self) -> int:
        if not self._instance.claim():
            self._hand_this_launch_over()
            return 0

        self._instance.serve_show_requests(self._show_window)
        self.start()
        return self._app.exec()

    def _hand_this_launch_over(self):
        """Give this launch to the Evolver already running, or say why not.

        A wedged instance holds the mutex while answering nothing, and exiting
        into silence there looks exactly like a shortcut that does nothing.
        """
        crash_log.write_info(
            "Already running:", "duplicate launch handed to the running instance\n",
        )
        if self._instance.hand_off():
            return
        show_error(
            "Evolver",
            "Evolver is already running but did not respond, so its window "
            "could not be opened.\n\nQuit it from the tray icon, or end the "
            "pythonw.exe process, then start Evolver again.",
        )

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

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

    def _show_stats(self):
        if self._stats_window is not None:
            if self._stats_window.isVisible():
                self._stats_window.raise_()
                self._stats_window.activateWindow()
                return
            # Closed, but parented to the main window, so one replaced without
            # being taken down stays alive for the process's whole life.
            self._stats_window.close()
            self._stats_window.deleteLater()
        records = load_runs(config.RUNS_DIR)
        self._stats_window = StatsWindow(records, self._window)
        self._stats_window.show()

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
        """Start the metadata backfill tool as its own process.

        Detached rather than in-process: it holds the microphone open and drives a
        media backend for as long as the user keeps labelling, and neither belongs
        in the tray process that has to survive the whole session.
        """
        subprocess.Popen(
            [sys.executable, str(config.PROJECT_DIR / "backfill_app.py")],
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
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._quit_by_request()

    def _restart(self):
        cmd = [sys.executable, str(config.PROJECT_DIR / "tray_app.py")]
        show = self._window.isVisible()
        if show:
            cmd.append("--show-window")
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        if show:
            ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
        self._shutdown()

    def _quit_by_request(self):
        """Quit because the user asked for it — the one quit the broker honors.

        Every other way Evolver goes down leaves no mark and is undone within the
        quarter hour: a crash, a kill from the task list, the quit above that
        Windows asks for when it announces a session end and then, sometimes,
        cancels. This one leaves a mark, so closing Evolver on purpose is not
        argued with. Starting it again clears the mark; see start().
        """
        peer_watch.stand_evolver_down()
        self._shutdown()

    def _shutdown(self):
        self._runs.wait_for_exit(5000)
        self._scheduler.stop()
        self._peer_timer.stop()
        self._tray.hide()
        self._app.quit()
